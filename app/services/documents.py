import re
from io import BytesIO
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

import pymupdf as fitz


def extract_pdf_text(content: bytes, max_chars: int = 60000) -> tuple[str, str]:
    """Extract text only; this is not authentication or legal validation of the document."""
    try:
        with fitz.open(stream=content, filetype="pdf") as pdf:
            if pdf.is_encrypted:
                return "", "pdf_encrypted"
            parts = []
            for page in pdf:
                parts.append(page.get_text("text"))
                if sum(map(len, parts)) >= max_chars:
                    break
            text = "\n".join(parts)[:max_chars].strip()
            return text, "text_extracted" if text else "no_readable_text"
    except Exception:
        return "", "pdf_unreadable"


def suggest_invoice_fields(text: str) -> dict:
    """Best-effort suggestions; every value must be reviewed by a person."""
    result: dict = {}
    if not text:
        return result
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        try:
            result["issue_date"] = date.fromisoformat(date_match.group(1)).isoformat()
        except ValueError:
            pass
    number_match = re.search(r"(?i)\b(?:fatura|factura|invoice)\s*(?:n[.ºo°]*\s*)?[:#-]?\s*([A-Z0-9./_-]{2,30})", text)
    if number_match:
        result["number"] = number_match.group(1).strip()
    amount_matches = re.findall(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*[,.]\d{2})(?!\d)", text)
    if amount_matches:
        candidates = []
        for raw in amount_matches:
            normalized = raw.replace(" ", "").replace(".", "").replace(",", ".")
            try:
                candidates.append(Decimal(normalized))
            except InvalidOperation:
                continue
        if candidates:
            result["possible_amounts"] = [str(v.quantize(Decimal("0.01"))) for v in candidates[-5:]]
    result["requires_human_review"] = True
    return result


def detect_file_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None



def parse_portuguese_invoice_qr(payload: str) -> dict:
    """Parse AT QR payload fields. This is extraction, not authenticity verification."""
    fields: dict[str, list[str]] = {}
    warnings: list[str] = []
    for part in (payload or "").split("*"):
        if ":" not in part:
            if part.strip():
                warnings.append("Existe um segmento QR que não segue o formato campo:valor.")
            continue
        key, value = part.split(":", 1)
        key = key.strip().upper()
        value = value.strip()
        if not re.fullmatch(r"(?:[A-Z]|I\d{1,2})", key):
            warnings.append("Foi encontrado um campo QR não reconhecido.")
            continue
        fields.setdefault(key, []).append(value)

    def first(key: str) -> str | None:
        values = fields.get(key, [])
        return values[0] if values else None

    def money(key: str) -> str | None:
        value = first(key)
        if not value:
            return None
        try:
            amount = Decimal(value)
            if not amount.is_finite():
                return None
            return str(amount.quantize(Decimal("0.01")))
        except (InvalidOperation, ValueError):
            warnings.append(f"O valor do campo {key} não pôde ser interpretado como montante.")
            return None

    issue_date = None
    raw_date = first("F")
    if raw_date:
        try:
            issue_date = date.fromisoformat(f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}").isoformat() if re.fullmatch(r"\d{8}", raw_date) else None
        except ValueError:
            issue_date = None
        if not issue_date:
            warnings.append("A data do documento no QR não tem formato válido.")

    required_keys = ["A", "D", "E", "F", "G", "O"]
    missing = [key for key in required_keys if not first(key)]
    if missing:
        warnings.append("Campos QR não encontrados: " + ", ".join(missing) + ".")

    tax_fields = {key: values[0] for key, values in fields.items() if key.startswith("I") and key[1:].isdigit()}
    return {
        "issuer_nif": first("A"),
        "customer_nif": first("B"),
        "customer_country": first("C"),
        "document_type": first("D"),
        "document_status": first("E"),
        "issue_date": issue_date,
        "document_identifier": first("G"),
        "atcud": first("H"),
        "tax_total": money("N"),
        "total_amount": money("O"),
        "tax_fields": tax_fields,
        "other_information": first("S"),
        "qr_hash_fragment": first("Q"),
        "certificate_number": first("R"),
        "warnings": warnings,
        "requires_human_review": True,
    }


def extract_portuguese_invoice_qr(content: bytes, mime_type: str, max_pages: int = 5) -> dict:
    """Read QR codes from invoice PDFs/images. Parsed values must always be reviewed by a person."""
    try:
        import numpy as np
        import zxingcpp
        from PIL import Image
    except ImportError:
        return {"status": "decoder_unavailable", "records": [], "warnings": ["O leitor de QR não está instalado."]}

    arrays = []
    try:
        if mime_type == "application/pdf":
            with fitz.open(stream=content, filetype="pdf") as pdf:
                for page in list(pdf)[:max_pages]:
                    pix = page.get_pixmap(dpi=200, alpha=False)
                    if pix.width * pix.height > 15_000_000:
                        continue
                    arrays.append(np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n).copy())
        elif mime_type in {"image/png", "image/jpeg"}:
            with Image.open(BytesIO(content)) as image:
                image = image.convert("RGB")
                if image.width * image.height <= 15_000_000:
                    arrays.append(np.asarray(image))
        else:
            return {"status": "unsupported_format", "records": [], "warnings": ["Formato não suportado para leitura QR."]}
    except Exception:
        return {"status": "unreadable", "records": [], "warnings": ["O ficheiro não pôde ser preparado para leitura QR."]}

    payloads = []
    seen = set()
    for array in arrays:
        try:
            barcodes = zxingcpp.read_barcodes(array)
        except Exception:
            continue
        for barcode in barcodes:
            fmt = str(getattr(barcode, "format", "")).lower()
            if "qr" not in fmt:
                continue
            payload = str(getattr(barcode, "text", "") or "").strip()
            if payload and payload not in seen:
                seen.add(payload)
                payloads.append(payload[:5000])
    if not payloads:
        return {"status": "not_found", "records": [], "warnings": ["Não foi detetado um código QR legível."]}
    records = [parse_portuguese_invoice_qr(payload) for payload in payloads[:5]]
    return {"status": "decoded_for_review", "records": records,
            "warnings": ["A leitura do QR não confirma a autenticidade da fatura nem a situação fiscal do emitente."]}
