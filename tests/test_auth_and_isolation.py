import re
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Company, Membership, Subcontractor, User
from app.security import hash_password


def _create_user_company(role="owner"):
    suffix = uuid4().hex
    db = SessionLocal()
    try:
        user = User(
            email=f"test-{suffix}@example.invalid",
            password_hash=hash_password("test-password-at-least-12"),
            email_verified=True,
        )
        db.add(user)
        db.flush()
        company = Company(name=f"Empresa {suffix[:8]}", nif="", email=user.email, iban="")
        db.add(company)
        db.flush()
        db.add(Membership(user_id=user.id, company_id=company.id, role=role))
        db.commit()
        return user.id, company.id, user.email
    finally:
        db.close()


def _login(client: TestClient, email: str):
    page = client.get("/login")
    csrf_match = re.search(r'name="csrf" value="([^"]+)"', page.text)
    assert csrf_match
    response = client.post(
        "/login",
        data={"email": email, "password": "test-password-at-least-12", "csrf": csrf_match.group(1)},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_login_and_cross_company_vendor_isolation():
    with TestClient(app) as client:
        _, company_a_id, email_a = _create_user_company("owner")
        _, company_b_id, _ = _create_user_company("owner")
        db = SessionLocal()
        try:
            vendor = Subcontractor(company_id=company_b_id, name="Fornecedor Privado", nif="", email="", iban="")
            db.add(vendor)
            db.commit()
            vendor_id = vendor.id
        finally:
            db.close()

        _login(client, email_a)
        assert client.get("/dashboard").status_code == 200
        response = client.get(f"/vendors/{vendor_id}")
        assert response.status_code == 404
        assert "Fornecedor Privado" not in response.text


def test_viewer_cannot_create_vendor_and_csrf_is_required():
    with TestClient(app) as client:
        _, company_id, email = _create_user_company("viewer")
        _login(client, email)
        page = client.get("/vendors/new")
        assert page.status_code == 200
        response = client.post("/vendors/new", data={
            "name": "Não autorizado", "nif": "", "email": "", "phone": "",
            "iban": "", "notes": "", "csrf": re.search(r'name="csrf" value="([^"]+)"', page.text).group(1),
        }, follow_redirects=False)
        assert response.status_code == 403

        # A write request without the CSRF token must fail before changing data.
        response = client.post("/vendors/new", data={"name": "Sem CSRF", "csrf": ""}, follow_redirects=False)
        assert response.status_code == 400

        db = SessionLocal()
        try:
            assert db.query(Subcontractor).filter(
                Subcontractor.company_id == company_id, Subcontractor.name == "Não autorizado"
            ).count() == 0
        finally:
            db.close()
