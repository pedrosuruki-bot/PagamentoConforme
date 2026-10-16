import csv
import hashlib
import io
import json
import logging
import secrets
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

import httpx
import stripe
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from app.config import get_settings
from app.db import Base, SessionLocal, engine, get_db
from app.models import AuditLog, Company, Document, Invoice, Membership, PaymentBatch, PaymentBatchItem, SubmissionLink, Subcontractor, Subscription, User, WebhookEvent, VendorImportBatch
from app.security import csrf_token, hash_password, make_submission_token, read_submission_token, token_hash, verify_csrf, verify_password
from app.services.documents import detect_file_type, extract_pdf_text, suggest_invoice_fields
from app.services.sepa import build_pain001, validate_draft_xml
from app.storage import put_private_file, read_private_file
from app.validators import normalize_iban, normalize_nif, safe_filename, validate_iban, validate_portuguese_nif

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pagamentoconforme")
settings = get_settings()

app = FastAPI(title=settings.app_name, version="0.1.0")
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="pc_session",
    max_age=settings.session_max_age_seconds,
    same_site="lax",
    https_only=settings.session_https_only,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.on_event("startup")
def startup():
    if settings.is_production and settings.secret_key == "local-development-only-change-me":
        raise RuntimeError("SECRET_KEY tem de ser configurada em produção.")
    if not settings.is_production:
        Base.metadata.create_all(bind=engine)
    Path(settings.private_storage_dir).mkdir(parents=True, exist_ok=True)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.url.path.startswith(("/dashboard", "/vendors", "/invoices", "/batches", "/billing", "/documents")):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


def render(request: Request, template: str, status_code: int = 200, **context):
    context.setdefault("csrf_token", csrf_token(request))
    context.setdefault("current_user", None)
    context.setdefault("current_company", None)
    return templates.TemplateResponse(
        request=request, name=template, context=context, status_code=status_code
    )


def current_context(request: Request, db: Session):
    user_id = request.session.get("user_id")
    company_id = request.session.get("company_id")
    if not user_id or not company_id:
        return None
    user = db.get(User, int(user_id))
    company = db.get(Company, int(company_id))
    membership = db.scalar(
        select(Membership).where(
            Membership.user_id == int(user_id),
            Membership.company_id == int(company_id),
        )
    )
    if (not user or not company or not membership or not user.email_verified
            or request.session.get("session_version") != user.session_version):
        request.session.clear()
        return None
    return {"user": user, "company": company, "membership": membership}


def require_context(request: Request, db: Session):
    ctx = current_context(request, db)
    if not ctx:
        raise HTTPException(status_code=401, detail="Sessão inválida.")
    return ctx


def require_roles(ctx: dict, allowed_roles: set[str]):
    if ctx["membership"].role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Não tem permissões para executar esta operação.")


def audit(db: Session, company_id: int, user_id: int | None, action: str,
          entity_type: str, entity_id: str, details: dict | None = None):
    db.add(AuditLog(
        company_id=company_id, user_id=user_id, action=action,
        entity_type=entity_type, entity_id=str(entity_id), details=details or {},
    ))


def check_csrf_or_400(request: Request, supplied: str):
    if not verify_csrf(request, supplied):
        raise HTTPException(status_code=400, detail="A sessão do formulário expirou. Atualize a página e tente novamente.")


def email_verifier():
    return URLSafeTimedSerializer(settings.secret_key, salt="pc-email-verification")


def send_verification_email(email: str, token: str):
    verify_url = f"{settings.base_url.rstrip('/')}/verify-email?token={quote(token)}"
    if settings.resend_api_key and settings.email_from:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
            json={
                "from": settings.email_from,
                "to": [email],
                "subject": "Confirme o seu email — PagamentoConforme",
                "html": f"<p>Para confirmar o seu email, abra esta ligação:</p><p><a href=\"{verify_url}\">Confirmar email</a></p><p>Se não criou esta conta, ignore esta mensagem.</p>",
            },
            timeout=15,
        )
        if response.status_code >= 300:
            logger.error("Email verification provider rejected request: %s", response.status_code)
            return False
        return True
    if not settings.is_production:
        logger.info("Ligação de verificação para %s: %s", email, verify_url)
        return True
    logger.error("Email não enviado: configure RESEND_API_KEY e EMAIL_FROM.")
    return False


def get_owned_vendor(db: Session, company_id: int, vendor_id: int):
    vendor = db.scalar(select(Subcontractor).where(
        Subcontractor.id == vendor_id, Subcontractor.company_id == company_id
    ))
    if not vendor:
        raise HTTPException(status_code=404, detail="Subempreiteiro não encontrado.")
    return vendor


def get_owned_invoice(db: Session, company_id: int, invoice_id: int):
    invoice = db.scalar(select(Invoice).where(
        Invoice.id == invoice_id, Invoice.company_id == company_id
    ))
    if not invoice:
        raise HTTPException(status_code=404, detail="Fatura não encontrada.")
    return invoice


def upload_content(file: UploadFile) -> tuple[bytes, str]:
    content = file.file.read(settings.max_upload_mb * 1024 * 1024 + 1)
    if not content:
        raise HTTPException(status_code=400, detail="O ficheiro está vazio.")
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"O ficheiro excede o limite de {settings.max_upload_mb} MB.")
    mime = detect_file_type(content)
    if mime not in {"application/pdf", "image/png", "image/jpeg"}:
        raise HTTPException(status_code=400, detail="Formato não suportado. Envie um PDF, PNG ou JPEG.")
    return content, mime


def create_document(db: Session, company_id: int, vendor: Subcontractor,
                    kind: str, file: UploadFile, expires_on: date | None = None):
    content, mime = upload_content(file)
    original_name = safe_filename(file.filename or "document")
    key, digest = put_private_file(company_id, content, original_name, mime)
    text, extraction_status = extract_pdf_text(content) if mime == "application/pdf" else ("", "image_requires_review")
    doc = Document(
        company_id=company_id,
        subcontractor_id=vendor.id,
        kind=kind,
        upload_name=original_name,
        storage_key=key,
        mime_type=mime,
        size_bytes=len(content),
        sha256=digest,
        extracted_text=text,
        status=extraction_status if extraction_status != "text_extracted" else "review_required",
        expires_on=datetime.combine(expires_on, datetime.min.time()) if expires_on else None,
    )
    db.add(doc)
    db.flush()
    return doc, text


@app.get("/health")
def health():
    return {"status": "ok", "service": settings.app_name, "environment": settings.app_env}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, db: Session = Depends(get_db)):
    if current_context(request, db):
        return RedirectResponse("/dashboard", status_code=303)
    return render(request, "landing.html")


@app.get("/signup", response_class=HTMLResponse)
def signup_page(request: Request):
    return render(request, "signup.html")


@app.post("/signup", response_class=HTMLResponse)
def signup(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    company_name: str = Form(...),
    nif: str = Form(""),
    iban: str = Form(""),
    csrf: str = Form(...),
    db: Session = Depends(get_db),
):
    check_csrf_or_400(request, csrf)
    email = email.strip().lower()
    company_name = company_name.strip()
    nif = normalize_nif(nif)
    iban = normalize_iban(iban)
    if "@" not in email or len(email) > 320:
        return render(request, "signup.html", status_code=400, error="Indique um email válido.")
    if len(password) < 12:
        return render(request, "signup.html", status_code=400, error="A palavra-passe deve ter pelo menos 12 caracteres.")
    if not company_name or len(company_name) > 180:
        return render(request, "signup.html", status_code=400, error="Indique o nome da empresa.")
    if nif and not validate_portuguese_nif(nif):
        return render(request, "signup.html", status_code=400, error="O NIF não passou a validação de formato. Confirme os dígitos.")
    if iban and not validate_iban(iban):
        return render(request, "signup.html", status_code=400, error="O IBAN da empresa não passou a validação de formato.")
    if db.scalar(select(User).where(User.email == email)):
        return render(request, "signup.html", status_code=409, error="Já existe uma conta com este email.")
    user = User(email=email, password_hash=hash_password(password), email_verified=False)
    db.add(user)
    db.flush()
    company = Company(name=company_name, nif=nif, email=email, iban=iban)
    db.add(company)
    db.flush()
    db.add(Membership(user_id=user.id, company_id=company.id, role="owner"))
    db.add(Subscription(company_id=company.id, status="not_configured"))
    db.commit()
    token = email_verifier().dumps({"user_id": user.id, "email": email})
    if not send_verification_email(email, token):
        message = "A conta foi criada, mas o email de confirmação não foi enviado. Configure o serviço de email antes de continuar."
    else:
        message = "Conta criada. Confirme o email através da ligação enviada. No modo local, a ligação aparece na consola do servidor."
    return render(request, "login.html", notice=message)


@app.get("/verify-email", response_class=HTMLResponse)
def verify_email(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        data = email_verifier().loads(token, max_age=60 * 60 * 24)
    except (BadSignature, SignatureExpired):
        return render(request, "login.html", status_code=400, error="A ligação de confirmação é inválida ou expirou.")
    user = db.get(User, int(data.get("user_id", 0)))
    if not user or user.email != data.get("email"):
        return render(request, "login.html", status_code=400, error="Não foi possível confirmar esta conta.")
    user.email_verified = True
    db.commit()
    return render(request, "login.html", notice="Email confirmado. Já pode iniciar sessão.")


def password_reset_verifier():
    return URLSafeTimedSerializer(settings.secret_key, salt="pc-password-reset")


def send_password_reset_email(email: str, token: str):
    reset_url = f"{settings.base_url.rstrip('/')}/reset-password?token={quote(token)}"
    if settings.resend_api_key and settings.email_from:
        response = httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json"},
            json={
                "from": settings.email_from,
                "to": [email],
                "subject": "Recuperar acesso — PagamentoConforme",
                "html": f"<p>Recebemos um pedido para alterar a palavra-passe desta conta.</p><p><a href=\"{reset_url}\">Definir nova palavra-passe</a></p><p>A ligação expira em 60 minutos. Se não fez o pedido, ignore esta mensagem.</p>",
            },
            timeout=15,
        )
        if response.status_code >= 300:
            logger.error("Password reset provider rejected request: %s", response.status_code)
            return False
        return True
    if not settings.is_production:
        logger.info("Ligação de recuperação de palavra-passe para %s: %s", email, reset_url)
        return True
    logger.error("Email de recuperação não enviado: configure RESEND_API_KEY e EMAIL_FROM.")
    return False


@app.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return render(request, "forgot_password.html")


@app.post("/forgot-password", response_class=HTMLResponse)
def forgot_password(request: Request, email: str = Form(...), csrf: str = Form(...),
                    db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    normalized_email = email.strip().lower()
    user = db.scalar(select(User).where(User.email == normalized_email))
    if user and user.email_verified:
        token = password_reset_verifier().dumps({"user_id": user.id, "email": user.email, "session_version": user.session_version})
        send_password_reset_email(user.email, token)
    # Same response whether the account exists or not, to avoid revealing registered emails.
    return render(request, "forgot_password.html",
                  notice="Se existir uma conta confirmada com esse email, enviaremos uma ligação para recuperar o acesso.")


@app.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str, db: Session = Depends(get_db)):
    try:
        data = password_reset_verifier().loads(token, max_age=60 * 60)
    except (BadSignature, SignatureExpired):
        return render(request, "forgot_password.html", status_code=400,
                      error="A ligação de recuperação é inválida ou expirou. Peça uma nova ligação.")
    user = db.get(User, int(data.get("user_id", 0)))
    if (not user or user.email != data.get("email") or not user.email_verified
            or data.get("session_version") != user.session_version):
        return render(request, "forgot_password.html", status_code=400,
                      error="A ligação de recuperação não pode ser utilizada. Peça uma nova ligação.")
    return render(request, "reset_password.html", token=token)


@app.post("/reset-password", response_class=HTMLResponse)
def reset_password(request: Request, token: str = Form(...), password: str = Form(...),
                   password_confirm: str = Form(...), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    try:
        data = password_reset_verifier().loads(token, max_age=60 * 60)
    except (BadSignature, SignatureExpired):
        return render(request, "forgot_password.html", status_code=400,
                      error="A ligação de recuperação é inválida ou expirou. Peça uma nova ligação.")
    user = db.get(User, int(data.get("user_id", 0)))
    if (not user or user.email != data.get("email") or not user.email_verified
            or data.get("session_version") != user.session_version):
        return render(request, "forgot_password.html", status_code=400,
                      error="A ligação de recuperação não pode ser utilizada. Peça uma nova ligação.")
    if len(password) < 12:
        return render(request, "reset_password.html", status_code=400, token=token,
                      error="A palavra-passe deve ter pelo menos 12 caracteres.")
    if password != password_confirm:
        return render(request, "reset_password.html", status_code=400, token=token,
                      error="As palavras-passe não coincidem.")
    user.password_hash = hash_password(password)
    user.session_version += 1
    db.commit()
    return render(request, "login.html", notice="Palavra-passe alterada. Inicie sessão com a nova palavra-passe.")



@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html")


@app.post("/login", response_class=HTMLResponse)
def login(request: Request, email: str = Form(...), password: str = Form(...),
          csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    user = db.scalar(select(User).where(User.email == email.strip().lower()))
    if not user or not verify_password(password, user.password_hash):
        return render(request, "login.html", status_code=401, error="Email ou palavra-passe incorretos.")
    if not user.email_verified:
        return render(request, "login.html", status_code=403, error="Confirme o seu email antes de iniciar sessão.")
    membership = db.scalar(select(Membership).where(Membership.user_id == user.id).order_by(Membership.id))
    if not membership:
        return render(request, "login.html", status_code=403, error="A conta não está associada a uma empresa.")
    request.session.clear()
    request.session["user_id"] = user.id
    request.session["company_id"] = membership.company_id
    request.session["session_version"] = user.session_version
    csrf_token(request)
    return RedirectResponse("/dashboard", status_code=303)


@app.post("/logout")
def logout(request: Request, csrf: str = Form(...)):
    check_csrf_or_400(request, csrf)
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    cid = ctx["company"].id
    totals = {
        "vendors": db.scalar(select(func.count()).select_from(Subcontractor).where(Subcontractor.company_id == cid, Subcontractor.active.is_(True))) or 0,
        "invoices": db.scalar(select(func.count()).select_from(Invoice).where(Invoice.company_id == cid)) or 0,
        "review": db.scalar(select(func.count()).select_from(Invoice).where(Invoice.company_id == cid, Invoice.status == "review_required")) or 0,
        "documents": db.scalar(select(func.count()).select_from(Document).where(Document.company_id == cid, Document.status == "review_required")) or 0,
        "pending_amount": db.scalar(select(func.coalesce(func.sum(Invoice.total_amount), 0)).where(Invoice.company_id == cid, Invoice.status.in_(["review_required", "pending_documents", "ready_for_review"]))) or 0,
    }
    recent = list(db.scalars(select(Invoice).where(Invoice.company_id == cid).order_by(Invoice.created_at.desc()).limit(6)))
    return render(request, "dashboard.html", current_user=ctx["user"], current_company=ctx["company"], totals=totals, recent=recent)


@app.get("/settings/company", response_class=HTMLResponse)
def company_settings_page(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    return render(request, "company_settings.html", current_user=ctx["user"], current_company=ctx["company"],
                  company=ctx["company"], success=request.query_params.get("success"))


@app.post("/settings/company", response_class=HTMLResponse)
def update_company_settings(request: Request, name: str = Form(...), nif: str = Form(""),
                            email: str = Form(""), iban: str = Form(""), csrf: str = Form(...),
                            db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if ctx["membership"].role not in {"owner", "admin"}:
        raise HTTPException(status_code=403, detail="Só o proprietário ou administrador pode alterar a empresa.")
    name, nif, iban = name.strip(), normalize_nif(nif), normalize_iban(iban)
    email = email.strip().lower()
    error = None
    if not name or len(name) > 180:
        error = "Indique o nome da empresa."
    elif nif and not validate_portuguese_nif(nif):
        error = "O NIF não passou a validação de formato."
    elif iban and not validate_iban(iban):
        error = "O IBAN não passou a validação de formato."
    elif email and "@" not in email:
        error = "Indique um email válido."
    if error:
        return render(request, "company_settings.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], company=ctx["company"], error=error)
    company = ctx["company"]
    company.name, company.nif, company.email, company.iban = name, nif, email, iban
    audit(db, company.id, ctx["user"].id, "company.settings_updated", "company", company.id,
          {"name_changed": True, "nif_set": bool(nif), "iban_set": bool(iban)})
    db.commit()
    return RedirectResponse("/settings/company?success=saved", status_code=303)


@app.get("/vendors", response_class=HTMLResponse)
def vendors(request: Request, q: str = "", db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    query = select(Subcontractor).where(Subcontractor.company_id == ctx["company"].id)
    if q.strip():
        term = "%" + q.strip().replace("%", "") + "%"
        query = query.where((Subcontractor.name.ilike(term)) | (Subcontractor.nif.ilike(term)))
    rows = list(db.scalars(query.order_by(Subcontractor.name).limit(200)))
    return render(request, "vendors.html", current_user=ctx["user"], current_company=ctx["company"], vendors=rows, q=q)


@app.get("/vendors/import", response_class=HTMLResponse)
def vendor_import_page(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    return render(request, "vendor_import.html", current_user=ctx["user"],
                  current_company=ctx["company"])


@app.post("/vendors/import/preview", response_class=HTMLResponse)
def vendor_import_preview(request: Request, file: UploadFile = File(...),
                          csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    if file.filename and not file.filename.lower().endswith(".csv"):
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="Envie um ficheiro com extensão .csv.")
    content = file.file.read(1_000_001)
    if not content:
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="O ficheiro está vazio.")
    if len(content) > 1_000_000:
        return render(request, "vendor_import.html", status_code=413, current_user=ctx["user"],
                      current_company=ctx["company"], error="O ficheiro excede o limite de 1 MB.")
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="O CSV tem de estar codificado em UTF-8.")
    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="Não foram encontrados cabeçalhos no CSV.")
    aliases = {
        "name": "name", "nome": "name", "empresa": "name", "denominacao_social": "name",
        "nif": "nif", "vat": "nif", "email": "email", "e-mail": "email",
        "phone": "phone", "telefone": "phone", "telemovel": "phone",
        "iban": "iban", "notes": "notes", "notas": "notes",
    }
    column_map = {str(header or "").strip().lower(): str(header or "") for header in reader.fieldnames}
    normalized_headers = {key: aliases.get(key) for key in column_map}
    if "name" not in normalized_headers.values():
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="O CSV tem de conter uma coluna 'name' ou 'nome'.")
    existing_nifs = {
        v.nif for v in db.scalars(select(Subcontractor).where(
            Subcontractor.company_id == ctx["company"].id, Subcontractor.nif != ""
        ))
    }
    seen_nifs = set()
    rows = []
    for line_number, raw in enumerate(reader, start=2):
        if line_number > 502:
            return render(request, "vendor_import.html", status_code=413, current_user=ctx["user"],
                          current_company=ctx["company"], error="O CSV pode conter no máximo 500 linhas de dados.")
        normalized = {}
        for header, value in (raw or {}).items():
            alias = aliases.get(str(header or "").strip().lower())
            if alias:
                normalized[alias] = str(value or "").strip()
        row = {
            "line": line_number,
            "name": normalized.get("name", "")[:180],
            "nif": normalize_nif(normalized.get("nif", "")),
            "email": normalized.get("email", "").lower()[:320],
            "phone": normalized.get("phone", "")[:40],
            "iban": normalize_iban(normalized.get("iban", "")),
            "notes": normalized.get("notes", "")[:2000],
            "valid": True,
            "errors": [],
        }
        if not row["name"]:
            row["errors"].append("Nome em falta.")
        if row["nif"] and not validate_portuguese_nif(row["nif"]):
            row["errors"].append("NIF inválido.")
        if row["iban"] and not validate_iban(row["iban"]):
            row["errors"].append("IBAN inválido.")
        if row["email"] and "@" not in row["email"]:
            row["errors"].append("Email inválido.")
        if row["nif"] and row["nif"] in existing_nifs:
            row["errors"].append("NIF já registado nesta empresa.")
        if row["nif"] and row["nif"] in seen_nifs:
            row["errors"].append("NIF duplicado neste ficheiro.")
        if row["nif"]:
            seen_nifs.add(row["nif"])
        row["valid"] = not row["errors"]
        rows.append(row)
    if not rows:
        return render(request, "vendor_import.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], error="O CSV não contém linhas de dados.")
    batch = VendorImportBatch(
        company_id=ctx["company"].id,
        created_by_id=ctx["user"].id,
        rows=rows,
        status="staged",
        expires_at=datetime.utcnow() + timedelta(minutes=30),
    )
    db.add(batch)
    db.commit()
    return RedirectResponse(f"/vendors/import/{batch.id}/preview", status_code=303)


@app.get("/vendors/import/{batch_id}/preview", response_class=HTMLResponse)
def vendor_import_preview_page(request: Request, batch_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    batch = db.scalar(select(VendorImportBatch).where(
        VendorImportBatch.id == batch_id,
        VendorImportBatch.company_id == ctx["company"].id,
        VendorImportBatch.created_by_id == ctx["user"].id,
    ))
    if not batch or batch.status != "staged" or batch.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="A pré-visualização expirou ou já foi utilizada.")
    valid_count = sum(1 for row in batch.rows if row.get("valid"))
    invalid_count = len(batch.rows) - valid_count
    return render(request, "vendor_import_preview.html", current_user=ctx["user"],
                  current_company=ctx["company"], batch=batch, rows=batch.rows,
                  valid_count=valid_count, invalid_count=invalid_count)


@app.post("/vendors/import/{batch_id}/confirm")
def vendor_import_confirm(request: Request, batch_id: int, csrf: str = Form(...),
                          db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    batch = db.scalar(select(VendorImportBatch).where(
        VendorImportBatch.id == batch_id,
        VendorImportBatch.company_id == ctx["company"].id,
        VendorImportBatch.created_by_id == ctx["user"].id,
    ))
    if not batch or batch.status != "staged" or batch.expires_at < datetime.utcnow():
        raise HTTPException(status_code=410, detail="A pré-visualização expirou ou já foi utilizada.")
    valid_rows = [row for row in batch.rows if row.get("valid")]
    if not valid_rows:
        raise HTTPException(status_code=409, detail="Não existem linhas válidas para importar.")
    imported = 0
    for row in valid_rows:
        db.add(Subcontractor(
            company_id=ctx["company"].id, name=row["name"], nif=row["nif"],
            email=row["email"], phone=row["phone"], iban=row["iban"], notes=row["notes"],
        ))
        imported += 1
    batch.status = "imported"
    audit(db, ctx["company"].id, ctx["user"].id, "subcontractor.csv_imported", "vendor_import_batch",
          batch.id, {"imported": imported, "skipped": len(batch.rows) - imported})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Os dados mudaram desde a pré-visualização. Gere uma nova pré-visualização.")
    return RedirectResponse(f"/vendors?imported={imported}&skipped={len(batch.rows) - imported}", status_code=303)


@app.get("/vendors/new", response_class=HTMLResponse)
def vendor_new_page(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    return render(request, "vendor_form.html", current_user=ctx["user"], current_company=ctx["company"])


@app.post("/vendors/new", response_class=HTMLResponse)
def vendor_new(request: Request, name: str = Form(...), nif: str = Form(""),
               email: str = Form(""), phone: str = Form(""), iban: str = Form(""),
               notes: str = Form(""), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    name = name.strip()
    nif = normalize_nif(nif)
    iban = normalize_iban(iban)
    if not name or len(name) > 180:
        return render(request, "vendor_form.html", status_code=400, error="Indique o nome do subempreiteiro.", current_user=ctx["user"], current_company=ctx["company"])
    if nif and not validate_portuguese_nif(nif):
        return render(request, "vendor_form.html", status_code=400, error="O NIF não passou a validação de formato.", current_user=ctx["user"], current_company=ctx["company"])
    if iban and not validate_iban(iban):
        return render(request, "vendor_form.html", status_code=400, error="O IBAN não é válido.", current_user=ctx["user"], current_company=ctx["company"])
    vendor = Subcontractor(company_id=ctx["company"].id, name=name, nif=nif, email=email.strip().lower(),
                           phone=phone.strip(), iban=iban, notes=notes.strip())
    db.add(vendor)
    db.flush()
    audit(db, ctx["company"].id, ctx["user"].id, "subcontractor.created", "subcontractor", vendor.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render(request, "vendor_form.html", status_code=409, error="Já existe um subempreiteiro com esse NIF nesta empresa.", current_user=ctx["user"], current_company=ctx["company"])
    return RedirectResponse(f"/vendors/{vendor.id}", status_code=303)


@app.get("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
def vendor_edit_page(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    return render(request, "vendor_edit.html", current_user=ctx["user"],
                  current_company=ctx["company"], vendor=vendor)


@app.post("/vendors/{vendor_id}/edit", response_class=HTMLResponse)
def vendor_edit(request: Request, vendor_id: int, name: str = Form(...), nif: str = Form(""),
                email: str = Form(""), phone: str = Form(""), iban: str = Form(""),
                notes: str = Form(""), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    name, nif, iban = name.strip(), normalize_nif(nif), normalize_iban(iban)
    email = email.strip().lower()
    error = None
    if not name or len(name) > 180:
        error = "Indique o nome do subempreiteiro."
    elif nif and not validate_portuguese_nif(nif):
        error = "O NIF não passou a validação de formato."
    elif iban and not validate_iban(iban):
        error = "O IBAN não passou a validação de formato."
    elif email and "@" not in email:
        error = "Indique um email válido."
    if error:
        vendor.name, vendor.nif, vendor.email, vendor.phone, vendor.iban, vendor.notes = name, nif, email, phone.strip(), iban, notes.strip()
        return render(request, "vendor_edit.html", status_code=400, current_user=ctx["user"],
                      current_company=ctx["company"], vendor=vendor, error=error)
    vendor.name, vendor.nif, vendor.email = name, nif, email
    vendor.phone, vendor.iban, vendor.notes = phone.strip(), iban, notes.strip()
    audit(db, ctx["company"].id, ctx["user"].id, "subcontractor.updated", "subcontractor", vendor.id,
          {"nif_set": bool(nif), "iban_set": bool(iban)})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
        return render(request, "vendor_edit.html", status_code=409, current_user=ctx["user"],
                      current_company=ctx["company"], vendor=vendor,
                      error="Já existe outro subempreiteiro com esse NIF nesta empresa.")
    return RedirectResponse(f"/vendors/{vendor.id}", status_code=303)


@app.post("/vendors/{vendor_id}/archive")
def vendor_archive(request: Request, vendor_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin"})
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    vendor.active = False
    audit(db, ctx["company"].id, ctx["user"].id, "subcontractor.archived", "subcontractor", vendor.id)
    db.commit()
    return RedirectResponse(f"/vendors/{vendor.id}", status_code=303)


@app.get("/vendors/{vendor_id}", response_class=HTMLResponse)
def vendor_detail(request: Request, vendor_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    docs = list(db.scalars(select(Document).where(Document.company_id == ctx["company"].id, Document.subcontractor_id == vendor.id).order_by(Document.created_at.desc())))
    invoices = list(db.scalars(select(Invoice).where(Invoice.company_id == ctx["company"].id, Invoice.subcontractor_id == vendor.id).order_by(Invoice.created_at.desc())))
    return render(request, "vendor_detail.html", current_user=ctx["user"], current_company=ctx["company"], vendor=vendor, documents=docs, invoices=invoices, submission_url=request.query_params.get("submission_url"))


@app.post("/vendors/{vendor_id}/submission-link", response_class=HTMLResponse)
def create_submission_link(request: Request, vendor_id: int, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    now = datetime.utcnow()
    active_links = list(db.scalars(select(SubmissionLink).where(SubmissionLink.company_id == ctx["company"].id, SubmissionLink.subcontractor_id == vendor.id, SubmissionLink.revoked_at.is_(None))))
    for old in active_links:
        old.revoked_at = now
    link = SubmissionLink(company_id=ctx["company"].id, subcontractor_id=vendor.id,
                          token_hash="pending-" + secrets.token_hex(24),
                          expires_at=now + timedelta(days=30))
    db.add(link)
    db.flush()
    token = make_submission_token(str(link.id))
    link.token_hash = token_hash(token)
    audit(db, ctx["company"].id, ctx["user"].id, "submission_link.created", "submission_link", link.id)
    db.commit()
    url = f"{settings.base_url.rstrip('/')}/submit/{quote(token, safe='')}"
    docs = list(db.scalars(select(Document).where(Document.company_id == ctx["company"].id, Document.subcontractor_id == vendor.id).order_by(Document.created_at.desc())))
    invoices = list(db.scalars(select(Invoice).where(Invoice.company_id == ctx["company"].id, Invoice.subcontractor_id == vendor.id).order_by(Invoice.created_at.desc())))
    return render(request, "vendor_detail.html", current_user=ctx["user"], current_company=ctx["company"], vendor=vendor, documents=docs, invoices=invoices, submission_url=url)


@app.post("/vendors/{vendor_id}/documents", response_class=HTMLResponse)
def upload_vendor_document(request: Request, vendor_id: int, kind: str = Form(...),
                           expires_on: str = Form(""), file: UploadFile = File(...),
                           csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    require_roles(ctx, {"owner", "admin", "finance"})
    vendor = get_owned_vendor(db, ctx["company"].id, vendor_id)
    allowed = {"at_certificate", "social_security_certificate", "work_accident_insurance", "other"}
    if kind not in allowed:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")
    expiry = None
    if expires_on:
        try:
            expiry = date.fromisoformat(expires_on)
        except ValueError:
            raise HTTPException(status_code=400, detail="Data de validade inválida.")
    doc, _ = create_document(db, ctx["company"].id, vendor, kind, file, expiry)
    audit(db, ctx["company"].id, ctx["user"].id, "document.uploaded", "document", doc.id, {"kind": kind, "size": doc.size_bytes})
    db.commit()
    return RedirectResponse(f"/vendors/{vendor.id}", status_code=303)


@app.get("/submit/{token}", response_class=HTMLResponse)
def public_submission_page(request: Request, token: str, db: Session = Depends(get_db)):
    link = _valid_submission_link(token, db)
    if not link:
        return render(request, "submission.html", status_code=410, error="Esta ligação expirou ou foi revogada.", token=None)
    vendor = db.get(Subcontractor, link.subcontractor_id)
    return render(request, "submission.html", token=token, vendor_name=vendor.name if vendor else "Subempreiteiro", error=None)


def _valid_submission_link(token: str, db: Session):
    link_id = read_submission_token(token)
    if not link_id:
        return None
    try:
        lid = int(link_id)
    except ValueError:
        return None
    link = db.get(SubmissionLink, lid)
    if not link or link.revoked_at or link.expires_at < datetime.utcnow():
        return None
    if not secrets.compare_digest(link.token_hash, token_hash(token)):
        return None
    return link


@app.post("/submit/{token}", response_class=HTMLResponse)
def public_submission(request: Request, token: str, kind: str = Form(...),
                      number: str = Form(""), issue_date: str = Form(""), total_amount: str = Form(""),
                      expires_on: str = Form(""), file: UploadFile = File(...),
                      csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    link = _valid_submission_link(token, db)
    if not link:
        return render(request, "submission.html", status_code=410, error="Esta ligação expirou ou foi revogada.", token=None)
    vendor = get_owned_vendor(db, link.company_id, link.subcontractor_id)
    allowed = {"invoice", "at_certificate", "social_security_certificate", "work_accident_insurance", "other"}
    if kind not in allowed:
        raise HTTPException(status_code=400, detail="Tipo de documento inválido.")
    try:
        expiry = date.fromisoformat(expires_on) if expires_on else None
    except ValueError:
        return render(request, "submission.html", status_code=400, token=token, vendor_name=vendor.name, error="A data de validade é inválida.")
    doc, text_value = create_document(db, link.company_id, vendor, kind, file, expiry)
    if kind == "invoice":
        try:
            amount = Decimal(total_amount.replace(",", "."))
        except (InvalidOperation, AttributeError):
            db.rollback()
            return render(request, "submission.html", status_code=400, token=token, vendor_name=vendor.name, error="Indique o valor total da fatura.")
        if amount <= 0 or not number.strip():
            db.rollback()
            return render(request, "submission.html", status_code=400, token=token, vendor_name=vendor.name, error="Indique o número e o valor total da fatura.")
        invoice_date = None
        if issue_date:
            try:
                invoice_date = date.fromisoformat(issue_date)
            except ValueError:
                db.rollback()
                return render(request, "submission.html", status_code=400, token=token, vendor_name=vendor.name, error="A data da fatura é inválida.")
        db.add(Invoice(company_id=link.company_id, subcontractor_id=vendor.id, document_id=doc.id,
                       number=number.strip(), issue_date=invoice_date, total_amount=amount,
                       status="review_required", review_notes="Submetida através de link público; requer revisão humana."))
    audit(db, link.company_id, None, "document.public_submission", "document", doc.id, {"kind": kind})
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return render(request, "submission.html", status_code=409, token=token, vendor_name=vendor.name, error="Este documento pode duplicar um registo existente. Contacte a empresa para confirmar.")
    return render(request, "submission.html", token=token, vendor_name=vendor.name, success="Documento recebido. A empresa irá rever a informação.", error=None)


@app.get("/invoices", response_class=HTMLResponse)
def invoices_page(request: Request, status: str = "", db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    q = select(Invoice).where(Invoice.company_id == ctx["company"].id)
    if status in {"review_required", "approved", "batched", "paid", "pending_documents"}:
        q = q.where(Invoice.status == status)
    rows = list(db.scalars(q.order_by(Invoice.created_at.desc()).limit(300)))
    vendors_by_id = {v.id: v.name for v in db.scalars(select(Subcontractor).where(Subcontractor.company_id == ctx["company"].id))}
    return render(request, "invoices.html", current_user=ctx["user"], current_company=ctx["company"], invoices=rows, vendors=vendors_by_id, status=status)


@app.get("/invoices/{invoice_id}", response_class=HTMLResponse)
def invoice_detail(request: Request, invoice_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    invoice = get_owned_invoice(db, ctx["company"].id, invoice_id)
    vendor = get_owned_vendor(db, ctx["company"].id, invoice.subcontractor_id)
    document = db.get(Document, invoice.document_id) if invoice.document_id else None
    related_docs = list(db.scalars(select(Document).where(Document.company_id == ctx["company"].id, Document.subcontractor_id == vendor.id).order_by(Document.created_at.desc())))
    return render(request, "invoice_detail.html", current_user=ctx["user"], current_company=ctx["company"], invoice=invoice, vendor=vendor, document=document, related_docs=related_docs)


@app.post("/invoices/{invoice_id}/approve")
def approve_invoice(request: Request, invoice_id: int, csrf: str = Form(...), review_notes: str = Form(""), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if ctx["membership"].role not in {"owner", "admin", "finance"}:
        raise HTTPException(status_code=403, detail="Não tem permissões para aprovar faturas.")
    invoice = get_owned_invoice(db, ctx["company"].id, invoice_id)
    if invoice.status not in {"review_required", "pending_documents", "ready_for_review"}:
        raise HTTPException(status_code=409, detail="Esta fatura não está num estado que permita aprovação.")
    if invoice.status == "pending_documents" and not review_notes.strip():
        raise HTTPException(status_code=409, detail="A fatura tem documentação pendente. Registe uma justificação explícita para aprovar como exceção.")
    vendor = get_owned_vendor(db, ctx["company"].id, invoice.subcontractor_id)
    if not validate_iban(vendor.iban):
        return RedirectResponse(f"/invoices/{invoice.id}?error=iban", status_code=303)
    invoice.status = "approved"
    invoice.approved_by_id = ctx["user"].id
    invoice.approved_at = datetime.utcnow()
    invoice.review_notes = review_notes.strip()
    audit(db, ctx["company"].id, ctx["user"].id, "invoice.approved", "invoice", invoice.id, {"human_review": True})
    db.commit()
    return RedirectResponse(f"/invoices/{invoice.id}", status_code=303)


@app.post("/invoices/{invoice_id}/status")
def update_invoice_status(request: Request, invoice_id: int, status: str = Form(...),
                          review_notes: str = Form(""), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    invoice = get_owned_invoice(db, ctx["company"].id, invoice_id)
    if status not in {"review_required", "pending_documents", "cancelled"}:
        raise HTTPException(status_code=400, detail="Estado inválido.")
    if ctx["membership"].role not in {"owner", "admin", "finance"}:
        raise HTTPException(status_code=403, detail="Não tem permissões para alterar o estado.")
    invoice.status = status
    invoice.approved_by_id = None
    invoice.approved_at = None
    invoice.review_notes = review_notes.strip()
    audit(db, ctx["company"].id, ctx["user"].id, "invoice.status_changed", "invoice", invoice.id, {"status": status})
    db.commit()
    return RedirectResponse(f"/invoices/{invoice.id}", status_code=303)


@app.get("/documents/{document_id}/download")
def download_document(request: Request, document_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    doc = db.scalar(select(Document).where(Document.id == document_id, Document.company_id == ctx["company"].id))
    if not doc:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")
    content = read_private_file(doc.storage_key)
    audit(db, ctx["company"].id, ctx["user"].id, "document.downloaded", "document", doc.id)
    db.commit()
    return Response(content=content, media_type=doc.mime_type, headers={
        "Content-Disposition": f'attachment; filename="{safe_filename(doc.upload_name)}"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@app.get("/batches", response_class=HTMLResponse)
def batches_page(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    cid = ctx["company"].id
    batches = list(db.scalars(select(PaymentBatch).where(PaymentBatch.company_id == cid).order_by(PaymentBatch.created_at.desc())))
    available = list(db.scalars(select(Invoice).where(Invoice.company_id == cid, Invoice.status == "approved").order_by(Invoice.created_at.asc())))
    vendors = {v.id: v for v in db.scalars(select(Subcontractor).where(Subcontractor.company_id == cid))}
    return render(request, "batches.html", current_user=ctx["user"], current_company=ctx["company"], batches=batches, available=available, vendors=vendors, error=request.query_params.get("error"))


@app.post("/batches")
def create_batch(request: Request, invoice_ids: list[int] = Form([]), csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    company = ctx["company"]
    if ctx["membership"].role not in {"owner", "admin", "finance"}:
        raise HTTPException(status_code=403, detail="Não tem permissões para preparar lotes.")
    if not validate_iban(company.iban):
        return RedirectResponse("/batches?error=company-iban", status_code=303)
    ids = sorted(set(invoice_ids))
    if not ids:
        return RedirectResponse("/batches?error=empty", status_code=303)
    invoices = list(db.scalars(select(Invoice).where(Invoice.company_id == company.id, Invoice.id.in_(ids), Invoice.status == "approved")))
    if len(invoices) != len(ids):
        return RedirectResponse("/batches?error=eligibility", status_code=303)
    included = set(db.scalars(select(PaymentBatchItem.invoice_id).join(PaymentBatch, PaymentBatch.id == PaymentBatchItem.batch_id).where(PaymentBatch.company_id == company.id, PaymentBatchItem.invoice_id.in_(ids))))
    if included:
        return RedirectResponse("/batches?error=duplicate", status_code=303)
    vendors = {v.id: v for v in db.scalars(select(Subcontractor).where(Subcontractor.company_id == company.id, Subcontractor.id.in_({i.subcontractor_id for i in invoices})))}
    txs = []
    total = Decimal("0.00")
    for inv in invoices:
        vendor = vendors.get(inv.subcontractor_id)
        if not vendor or not validate_iban(vendor.iban):
            return RedirectResponse("/batches?error=beneficiary-iban", status_code=303)
        txs.append({"creditor_name": vendor.name, "creditor_iban": vendor.iban, "amount": inv.total_amount, "reference": inv.number})
        total += Decimal(inv.total_amount)
    reference = "PC-" + secrets.token_hex(6).upper()
    try:
        xml_content = build_pain001(
            message_id=reference, company_name=company.name, debtor_iban=company.iban,
            execution_date=date.today(), transactions=txs, creditor_bic=settings.payment_creditor_bic,
        )
    except (ValueError, InvalidOperation) as exc:
        logger.info("SEPA draft rejected during validation: %s", exc)
        return RedirectResponse("/batches?error=xml-validation", status_code=303)
    xml_errors = validate_draft_xml(xml_content)
    if xml_errors:
        logger.error("SEPA XML basic validation errors: %s", xml_errors)
        return RedirectResponse("/batches?error=xml-validation", status_code=303)
    batch = PaymentBatch(company_id=company.id, created_by_id=ctx["user"].id, reference=reference,
                         status="xml_generated_for_review", total_amount=total, xml_content=xml_content)
    db.add(batch)
    db.flush()
    for inv in invoices:
        db.add(PaymentBatchItem(batch_id=batch.id, invoice_id=inv.id))
        inv.status = "batched"
    audit(db, company.id, ctx["user"].id, "payment_batch.xml_generated", "payment_batch", batch.id,
          {"invoice_count": len(invoices), "total_amount": f"{total:.2f}"})
    db.commit()
    return RedirectResponse(f"/batches/{batch.id}", status_code=303)


@app.get("/batches/{batch_id}", response_class=HTMLResponse)
def batch_detail(request: Request, batch_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    batch = db.scalar(select(PaymentBatch).where(PaymentBatch.id == batch_id, PaymentBatch.company_id == ctx["company"].id))
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    items = list(db.scalars(select(PaymentBatchItem).where(PaymentBatchItem.batch_id == batch.id)))
    invoice_ids = [i.invoice_id for i in items]
    rows = list(db.scalars(select(Invoice).where(Invoice.company_id == ctx["company"].id, Invoice.id.in_(invoice_ids)))) if invoice_ids else []
    vendors = {v.id: v.name for v in db.scalars(select(Subcontractor).where(Subcontractor.company_id == ctx["company"].id))}
    return render(request, "batch_detail.html", current_user=ctx["user"], current_company=ctx["company"], batch=batch, invoices=rows, vendors=vendors, xml_errors=validate_draft_xml(batch.xml_content))


@app.get("/batches/{batch_id}/download")
def download_batch_xml(request: Request, batch_id: int, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    batch = db.scalar(select(PaymentBatch).where(PaymentBatch.id == batch_id, PaymentBatch.company_id == ctx["company"].id))
    if not batch:
        raise HTTPException(status_code=404, detail="Lote não encontrado.")
    audit(db, ctx["company"].id, ctx["user"].id, "payment_batch.xml_downloaded", "payment_batch", batch.id)
    db.commit()
    return Response(content=batch.xml_content.encode("utf-8"), media_type="application/xml",
                    headers={"Content-Disposition": f'attachment; filename="{batch.reference}.xml"', "Cache-Control": "private, no-store"})


@app.get("/billing", response_class=HTMLResponse)
def billing_page(request: Request, db: Session = Depends(get_db)):
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    sub = db.scalar(select(Subscription).where(Subscription.company_id == ctx["company"].id))
    return render(request, "billing.html", current_user=ctx["user"], current_company=ctx["company"], subscription=sub, stripe_ready=bool(settings.stripe_secret_key and settings.stripe_price_id_base))


@app.post("/billing/checkout")
def billing_checkout(request: Request, csrf: str = Form(...), db: Session = Depends(get_db)):
    check_csrf_or_400(request, csrf)
    ctx = current_context(request, db)
    if not ctx:
        return RedirectResponse("/login", status_code=303)
    if not (settings.stripe_secret_key and settings.stripe_price_id_base):
        return RedirectResponse("/billing?error=stripe-not-configured", status_code=303)
    stripe.api_key = settings.stripe_secret_key
    checkout = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[{"price": settings.stripe_price_id_base, "quantity": 1}],
        success_url=f"{settings.base_url.rstrip('/')}/billing?success=checkout",
        cancel_url=f"{settings.base_url.rstrip('/')}/billing?cancelled=checkout",
        client_reference_id=str(ctx["company"].id),
        metadata={"company_id": str(ctx["company"].id)},
        subscription_data={"metadata": {"company_id": str(ctx["company"].id)}},
    )
    return RedirectResponse(checkout.url, status_code=303)


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    if not settings.stripe_webhook_secret:
        raise HTTPException(status_code=503, detail="Webhook Stripe não configurado.")
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    except Exception:
        raise HTTPException(status_code=400, detail="Assinatura do webhook inválida.")
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not event_id or not event_type:
        raise HTTPException(status_code=400, detail="Evento Stripe sem identificador ou tipo.")
    existing = db.scalar(select(WebhookEvent).where(WebhookEvent.stripe_event_id == event_id))
    if existing:
        return {"received": True, "duplicate": True}

    obj = event.get("data", {}).get("object", {})
    metadata = obj.get("metadata") or {}
    company_id = metadata.get("company_id") or obj.get("client_reference_id")
    customer_id = str(obj.get("customer") or "")
    subscription_id = str(obj.get("subscription") or "")
    if event_type.startswith("customer.subscription."):
        subscription_id = str(obj.get("id") or subscription_id)
    sub = None
    if company_id and str(company_id).isdigit():
        sub = db.scalar(select(Subscription).where(Subscription.company_id == int(company_id)))
    if not sub and subscription_id:
        sub = db.scalar(select(Subscription).where(Subscription.stripe_subscription_id == subscription_id))
    if not sub and customer_id:
        sub = db.scalar(select(Subscription).where(Subscription.stripe_customer_id == customer_id))
    if not company_id and sub:
        company_id = sub.company_id
    company = db.get(Company, int(company_id)) if company_id and str(company_id).isdigit() else None

    if company and not sub:
        sub = Subscription(company_id=company.id)
        db.add(sub)
        db.flush()
    webhook_record = WebhookEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        company_id=company.id if company else None,
        status="unmatched" if not company else "received",
        error_summary="" if company else "Não foi possível associar o evento a uma empresa.",
    )
    db.add(webhook_record)
    db.flush()

    if company and sub:
        if customer_id:
            sub.stripe_customer_id = customer_id
        if event_type == "checkout.session.completed":
            sub.stripe_subscription_id = subscription_id or sub.stripe_subscription_id
            sub.status = "pending_confirmation"
        elif event_type.startswith("customer.subscription."):
            sub.stripe_subscription_id = subscription_id or sub.stripe_subscription_id
            raw_status = str(obj.get("status") or "")
            sub.status = raw_status or ("canceled" if event_type.endswith(".deleted") else sub.status)
            items = obj.get("items", {}).get("data", [])
            if items:
                price = items[0].get("price", {})
                sub.price_id = str(price.get("id") or sub.price_id)
        elif event_type == "invoice.paid":
            sub.status = "active"
        elif event_type == "invoice.payment_failed":
            sub.status = "past_due"
        sub.updated_at = datetime.utcnow()
        webhook_record.status = "processed"
        webhook_record.processed_at = datetime.utcnow()
        audit(db, company.id, None, "stripe.webhook_processed", "stripe_event", event_id, {"type": event_type})
    db.commit()
    return {"received": True, "matched": bool(company)}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    if exc.status_code == 401 and request.method == "GET":
        return RedirectResponse("/login", status_code=303)
    return render(request, "error.html", status_code=exc.status_code, error=str(exc.detail), current_user=None)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled application error on %s", request.url.path)
    return render(request, "error.html", status_code=500, error="Ocorreu um erro inesperado. O incidente foi registado.", current_user=None)
