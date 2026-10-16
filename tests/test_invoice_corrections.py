import re
from datetime import date, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Company, Invoice, Membership, Subcontractor, User
from app.security import hash_password


def _create_invoice(status="approved"):
    suffix = uuid4().hex
    db = SessionLocal()
    try:
        user = User(
            email=f"invoice-{suffix}@example.invalid",
            password_hash=hash_password("test-password-at-least-12"),
            email_verified=True,
        )
        db.add(user)
        db.flush()
        company = Company(name=f"Empresa fatura {suffix[:8]}", nif="", email=user.email, iban="")
        db.add(company)
        db.flush()
        db.add(Membership(user_id=user.id, company_id=company.id, role="owner"))
        vendor = Subcontractor(
            company_id=company.id, name=f"Fornecedor {suffix[:8]}",
            nif="", email="", phone="", iban="PT50000201231234567890154",
        )
        db.add(vendor)
        db.flush()
        invoice = Invoice(
            company_id=company.id, subcontractor_id=vendor.id,
            number="FT-ORIGINAL", issue_date=date(2026, 10, 1),
            total_amount=Decimal("120.00"), currency="EUR", status=status,
            approved_by_id=user.id if status == "approved" else None,
            approved_at=datetime.utcnow() if status == "approved" else None,
        )
        db.add(invoice)
        db.commit()
        return user.email, company.id, invoice.id, user.id
    finally:
        db.close()


def _csrf(client, path):
    page = client.get(path)
    assert page.status_code == 200
    match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert match
    return match.group(1)


def _login(client, email):
    csrf = _csrf(client, "/login")
    response = client.post(
        "/login",
        data={"email": email, "password": "test-password-at-least-12", "csrf": csrf},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_invoice_correction_resets_approval_and_records_audit():
    email, company_id, invoice_id, user_id = _create_invoice("approved")
    with TestClient(app) as client:
        _login(client, email)
        csrf = _csrf(client, f"/invoices/{invoice_id}")
        response = client.post(
            f"/invoices/{invoice_id}/edit",
            data={
                "csrf": csrf,
                "number": "FT-CORRIGIDA",
                "issue_date": "2026-10-02",
                "total_amount": "245.70",
                "correction_reason": "O total foi corrigido após comparar com o PDF original.",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    assert response.headers["location"].endswith("?success=corrected")
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == company_id).one()
        assert invoice.number == "FT-CORRIGIDA"
        assert invoice.issue_date == date(2026, 10, 2)
        assert invoice.total_amount == Decimal("245.70")
        assert invoice.status == "review_required"
        assert invoice.approved_at is None
        assert invoice.approved_by_id is None
        audit = db.query(AuditLog).filter(
            AuditLog.company_id == company_id,
            AuditLog.user_id == user_id,
            AuditLog.action == "invoice.corrected",
            AuditLog.entity_id == str(invoice_id),
        ).one()
        assert audit.details["reason"].startswith("O total foi corrigido")
    finally:
        db.close()


def test_invoice_in_batch_cannot_be_corrected():
    email, company_id, invoice_id, _ = _create_invoice("batched")
    with TestClient(app) as client:
        _login(client, email)
        csrf = _csrf(client, f"/invoices/{invoice_id}")
        response = client.post(
            f"/invoices/{invoice_id}/edit",
            data={
                "csrf": csrf, "number": "FT-EDITADA", "issue_date": "",
                "total_amount": "80.00", "correction_reason": "Teste de bloqueio",
            },
            follow_redirects=False,
        )
    assert response.status_code == 409
    db = SessionLocal()
    try:
        invoice = db.query(Invoice).filter(Invoice.id == invoice_id, Invoice.company_id == company_id).one()
        assert invoice.number == "FT-ORIGINAL"
        assert invoice.status == "batched"
    finally:
        db.close()


def test_invoice_correction_rejects_invalid_amounts():
    email, _, invoice_id, _ = _create_invoice("review_required")
    with TestClient(app) as client:
        _login(client, email)
        csrf = _csrf(client, f"/invoices/{invoice_id}")
        response = client.post(
            f"/invoices/{invoice_id}/edit",
            data={
                "csrf": csrf, "number": "FT-BAD", "issue_date": "",
                "total_amount": "NaN", "correction_reason": "Teste de valor inválido",
            },
            follow_redirects=False,
        )
    assert response.status_code == 400
