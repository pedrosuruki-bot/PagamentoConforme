import html
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

import httpx
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.db import SessionLocal
from app.models import Company, Document, EmailNotification, Membership, Subcontractor, User
from app.services.document_reminders import days_until_expiry, reminder_stage
from app.services.document_status import lisbon_today

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("pagamentoconforme.reminders")
settings = get_settings()


def recipient_for_company(db, company: Company) -> str:
    if company.email and "@" in company.email:
        return company.email
    owner_membership = db.scalar(
        select(Membership).where(
            Membership.company_id == company.id,
            Membership.role == "owner",
        ).order_by(Membership.id)
    )
    if owner_membership:
        owner = db.get(User, owner_membership.user_id)
        if owner and owner.email_verified:
            return owner.email
    return ""


def send_reminder(recipient: str, company_name: str, vendor_name: str,
                  document_kind: str, expiry_date: str, is_expired: bool) -> None:
    if not (settings.resend_api_key and settings.email_from):
        raise RuntimeError("Configure RESEND_API_KEY e EMAIL_FROM antes de ativar alertas.")
    subject = (
        f"Documento expirado — {vendor_name}"
        if is_expired else f"Documento próximo da validade — {vendor_name}"
    )
    state = "ultrapassou a data de validade indicada" if is_expired else "tem a data de validade próxima"
    html_body = (
        f"<p>Olá,</p><p>O documento <strong>{html.escape(document_kind)}</strong> do subempreiteiro "
        f"<strong>{html.escape(vendor_name)}</strong> {state} (<strong>{html.escape(expiry_date)}</strong>).</p>"
        f"<p>Empresa: {html.escape(company_name)}.</p>"
        "<p>Este aviso baseia-se na data registada e não confirma a autenticidade do documento nem a situação fiscal do fornecedor. "
        "Reveja o documento original e atualize o registo, se necessário.</p>"
        "<p>PagamentoConforme</p>"
    )
    response = httpx.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {settings.resend_api_key}",
            "Content-Type": "application/json",
        },
        json={"from": settings.email_from, "to": [recipient], "subject": subject, "html": html_body},
        timeout=20,
    )
    if response.status_code >= 300:
        raise RuntimeError(f"O fornecedor de email rejeitou o envio (HTTP {response.status_code}).")


def run_reminders(today=None) -> dict:
    today = today or lisbon_today()
    sent = skipped = failed = 0
    if not (settings.resend_api_key and settings.email_from):
        raise RuntimeError("Configure RESEND_API_KEY e EMAIL_FROM antes de ativar alertas.")
    db = SessionLocal()
    try:
        docs = list(db.scalars(
            select(Document).where(Document.expires_on.is_not(None)).order_by(Document.company_id, Document.id)
        ))
        for doc in docs:
            expiry_date = doc.expires_on.date()
            remaining = days_until_expiry(expiry_date, today)
            stage = reminder_stage(remaining if remaining is not None else 99999)
            if not stage:
                continue
            notification_type, period_key = stage
            company = db.get(Company, doc.company_id)
            vendor = db.get(Subcontractor, doc.subcontractor_id)
            if not company or not vendor:
                skipped += 1
                continue
            recipient = recipient_for_company(db, company)
            if not recipient:
                logger.warning("Sem email de destino configurado para empresa_id=%s", company.id)
                skipped += 1
                continue
            notice = db.scalar(select(EmailNotification).where(
                EmailNotification.document_id == doc.id,
                EmailNotification.notification_type == notification_type,
                EmailNotification.period_key == period_key,
            ))
            if notice and notice.status == "sent":
                skipped += 1
                continue
            if notice and notice.status == "sending" and notice.attempted_at and notice.attempted_at > datetime.utcnow() - timedelta(minutes=30):
                skipped += 1
                continue
            if notice is None:
                notice = EmailNotification(
                    company_id=company.id,
                    document_id=doc.id,
                    recipient_email=recipient,
                    notification_type=notification_type,
                    period_key=period_key,
                    status="sending",
                    attempted_at=datetime.utcnow(),
                    attempt_count=1,
                )
                db.add(notice)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    skipped += 1
                    continue
            else:
                notice.status = "sending"
                notice.recipient_email = recipient
                notice.attempted_at = datetime.utcnow()
                notice.attempt_count += 1
                notice.last_error = ""
                db.commit()
            try:
                send_reminder(
                    recipient, company.name, vendor.name, doc.kind,
                    expiry_date.isoformat(), remaining is not None and remaining < 0,
                )
                notice.status = "sent"
                notice.sent_at = datetime.utcnow()
                notice.last_error = ""
                db.commit()
                sent += 1
            except Exception as exc:
                db.rollback()
                current_notice = db.scalar(select(EmailNotification).where(
                    EmailNotification.document_id == doc.id,
                    EmailNotification.notification_type == notification_type,
                    EmailNotification.period_key == period_key,
                ))
                if current_notice:
                    current_notice.status = "failed"
                    current_notice.last_error = str(exc)[:500]
                    db.commit()
                logger.exception("Falha ao enviar alerta de documento id=%s", doc.id)
                failed += 1
        return {"sent": sent, "skipped": skipped, "failed": failed}
    finally:
        db.close()


if __name__ == "__main__":
    summary = run_reminders()
    print(f"Alertas enviados: {summary['sent']}; ignorados: {summary['skipped']}; falhados: {summary['failed']}")
