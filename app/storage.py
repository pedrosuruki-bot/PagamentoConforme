import hashlib
import mimetypes
import os
import secrets
from pathlib import Path
from urllib.parse import quote

import httpx
from fastapi import HTTPException

from app.config import get_settings


def _supabase_enabled() -> bool:
    settings = get_settings()
    return bool(settings.supabase_url and settings.supabase_service_role_key)


def put_private_file(company_id: int, content: bytes, original_name: str, mime_type: str) -> tuple[str, str]:
    settings = get_settings()
    digest = hashlib.sha256(content).hexdigest()
    suffix = Path(original_name).suffix.lower()[:10]
    key = f"{company_id}/{secrets.token_hex(16)}{suffix}"
    if _supabase_enabled():
        base = settings.supabase_url.rstrip("/")
        bucket = quote(settings.supabase_storage_bucket, safe="")
        obj = quote(key, safe="/")
        response = httpx.post(
            f"{base}/storage/v1/object/{bucket}/{obj}",
            content=content,
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
                "Content-Type": mime_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream",
                "x-upsert": "false",
            },
            timeout=30,
        )
        if response.status_code >= 300:
            raise HTTPException(status_code=502, detail="Não foi possível guardar o documento no armazenamento privado.")
        return key, digest

    if settings.is_production:
        raise HTTPException(status_code=503, detail="Armazenamento privado não configurado. Configure o Supabase Storage antes de receber documentos em produção.")
    root = Path(settings.private_storage_dir).resolve()
    destination = (root / key).resolve()
    if root not in destination.parents:
        raise HTTPException(status_code=400, detail="Caminho de armazenamento inválido.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return key, digest


def read_private_file(key: str) -> bytes:
    settings = get_settings()
    if not key or ".." in Path(key).parts or key.startswith(("/", "\\")):
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    if _supabase_enabled():
        base = settings.supabase_url.rstrip("/")
        bucket = quote(settings.supabase_storage_bucket, safe="")
        obj = quote(key, safe="/")
        response = httpx.get(
            f"{base}/storage/v1/object/{bucket}/{obj}",
            headers={
                "Authorization": f"Bearer {settings.supabase_service_role_key}",
                "apikey": settings.supabase_service_role_key,
            },
            timeout=30,
        )
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail="Documento não encontrado.")
        if response.status_code >= 300:
            raise HTTPException(status_code=502, detail="Falha ao obter documento do armazenamento privado.")
        return response.content
    root = Path(settings.private_storage_dir).resolve()
    destination = (root / key).resolve()
    if root not in destination.parents or not destination.is_file():
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    return destination.read_bytes()



def delete_private_file(key: str) -> None:
    """Best-effort cleanup for files whose database transaction did not complete."""
    settings = get_settings()
    if not key or ".." in Path(key).parts or key.startswith(("/", "\\")):
        return
    if _supabase_enabled():
        base = settings.supabase_url.rstrip("/")
        bucket = quote(settings.supabase_storage_bucket, safe="")
        obj = quote(key, safe="/")
        try:
            response = httpx.delete(
                f"{base}/storage/v1/object/{bucket}/{obj}",
                headers={
                    "Authorization": f"Bearer {settings.supabase_service_role_key}",
                    "apikey": settings.supabase_service_role_key,
                },
                timeout=15,
            )
            if response.status_code >= 300:
                import logging
                logging.getLogger("pagamentoconforme.storage").warning(
                    "Private file cleanup failed with status %s", response.status_code
                )
        except httpx.HTTPError:
            import logging
            logging.getLogger("pagamentoconforme.storage").exception("Private file cleanup request failed")
        return

    root = Path(settings.private_storage_dir).resolve()
    destination = (root / key).resolve()
    if root not in destination.parents:
        return
    try:
        destination.unlink(missing_ok=True)
    except OSError:
        import logging
        logging.getLogger("pagamentoconforme.storage").exception("Local private file cleanup failed")
