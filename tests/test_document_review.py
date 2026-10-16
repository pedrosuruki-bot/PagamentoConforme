import re
from datetime import datetime
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import AuditLog, Company, Document, Membership, Subcontractor, User
from app.security import hash_password


def _create_document():
    db = SessionLocal()
    try:
        suffix = uuid4().hex
        user = User(
            email=f"doc-review-{suffix}@example.invalid",
            password_hash=hash_password("test-password-at-least-12"),
            email_verified=True,
        )
        db.add(user)
        db.flush()
        company = Company(name=f"Empresa revisão {suffix[:8]}", nif="", email=user.email, iban="")
        db.add(company)
        db.flush()
        db.add(Membership(user_id=user.id, company_id=company.id, role="owner"))
        vendor = Subcontractor(
            company_id=company.id, name=f"Fornecedora {suffix[:8]}",
            nif="", email="", phone="", iban="",
        )
        db.add(vendor)
        db.flush()
        doc = Document(
            company_id=company.id,
            subcontractor_id=vendor.id,
            kind="at_certificate",
            upload_name="certidao-teste.pdf",
            storage_key=f"{company.id}/test.pdf",
            mime_type="application/pdf",
            size_bytes=12,
            sha256="a" * 64,
            extracted_text="",
            extracted_fields={},
            status="review_required",
            expires_on=datetime(2026, 11, 20),
        )
        db.add(doc)
        db.commit()
        return user.email, user.id, company.id, vendor.id, doc.id
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


def test_human_document_review_updates_state_and_creates_audit():
    email, user_id, company_id, vendor_id, document_id = _create_document()
    with TestClient(app) as client:
        _login(client, email)
        csrf = _csrf(client, f"/documents/{document_id}/review")
        response = client.post(
            f"/documents/{document_id}/review",
            data={
                "csrf": csrf,
                "review_status": "reviewed_by_human",
                "expires_on": "2026-12-31",
                "review_notes": "Conferi o documento original e a data indicada.",
            },
            follow_redirects=False,
        )
    assert response.status_code == 303
    db = SessionLocal()
    try:
        doc = db.query(Document).filter(Document.id == document_id, Document.company_id == company_id).one()
        assert doc.status == "reviewed_by_human"
        assert doc.reviewed_by_id == user_id
        assert doc.reviewed_at is not None
        assert doc.expires_on.date().isoformat() == "2026-12-31"
        assert "documento original" in doc.review_notes
        entry = db.query(AuditLog).filter(
            AuditLog.company_id == company_id,
            AuditLog.user_id == user_id,
            AuditLog.action == "document.reviewed",
            AuditLog.entity_id == str(document_id),
        ).one()
        assert entry.details["new"]["status"] == "reviewed_by_human"
        assert entry.details["new"]["expires_on"] == "2026-12-31"
    finally:
        db.close()


def test_document_review_does_not_expose_other_company_document():
    email, _, _, _, own_doc = _create_document()
    db = SessionLocal()
    try:
        suffix = uuid4().hex
        owner = User(email=f"other-{suffix}@example.invalid",
                     password_hash=hash_password("test-password-at-least-12"),
                     email_verified=True)
        db.add(owner)
        db.flush()
        company = Company(name=f"Outra Empresa {suffix[:8]}", nif="", email=owner.email, iban="")
        db.add(company)
        db.flush()
        db.add(Membership(user_id=owner.id, company_id=company.id, role="owner"))
        vendor = Subcontractor(company_id=company.id, name="Outro fornecedor",
                               nif="", email="", phone="", iban="")
        db.add(vendor)
        db.flush()
        other_doc = Document(
            company_id=company.id, subcontractor_id=vendor.id, kind="other",
            upload_name="privado.pdf", storage_key=f"{company.id}/private.pdf",
            mime_type="application/pdf", size_bytes=12, sha256="b"*64,
            extracted_text="", extracted_fields={}, status="review_required",
        )
        db.add(other_doc)
        db.commit()
        other_id = other_doc.id
    finally:
        db.close()
    with TestClient(app) as client:
        _login(client, email)
        response = client.get(f"/documents/{other_id}/review")
    assert response.status_code == 404
