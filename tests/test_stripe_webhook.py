import json
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Company, Subscription


def _company_with_subscription(status="active", last_event=300):
    db = SessionLocal()
    try:
        suffix = uuid4().hex
        company = Company(name=f"Stripe Test {suffix[:8]}", nif="", email=f"{suffix}@example.invalid")
        db.add(company)
        db.flush()
        subscription = Subscription(
            company_id=company.id,
            stripe_customer_id=f"cus_{suffix}",
            stripe_subscription_id=f"sub_{suffix}",
            status=status,
            last_stripe_event_created=last_event,
        )
        db.add(subscription)
        db.commit()
        return company.id, f"cus_{suffix}", f"sub_{suffix}"
    finally:
        db.close()


def _mock_event(monkeypatch, event):
    monkeypatch.setattr("app.main.settings.stripe_webhook_secret", "whsec_test")
    monkeypatch.setattr("app.main.stripe.Webhook.construct_event", lambda payload, signature, secret: event)


def test_stale_stripe_invoice_event_does_not_override_newer_subscription(monkeypatch):
    company_id, customer_id, subscription_id = _company_with_subscription("active", 300)
    event = {
        "id": "evt_stale_" + uuid4().hex,
        "type": "invoice.payment_failed",
        "created": 250,
        "data": {"object": {
            "id": "in_stale",
            "customer": customer_id,
            "parent": {"subscription_details": {"subscription": subscription_id}},
        }},
    }
    _mock_event(monkeypatch, event)
    with TestClient(app) as client:
        response = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "mock-signature"})
    assert response.status_code == 200
    assert response.json()["matched"] is True

    db = SessionLocal()
    try:
        subscription = db.query(Subscription).filter(Subscription.company_id == company_id).one()
        assert subscription.status == "active"
        assert subscription.last_stripe_event_created == 300
    finally:
        db.close()


def test_repeated_stripe_event_is_idempotent(monkeypatch):
    _, customer_id, subscription_id = _company_with_subscription("past_due", 100)
    event = {
        "id": "evt_repeat_" + uuid4().hex,
        "type": "invoice.paid",
        "created": 200,
        "data": {"object": {
            "id": "in_paid",
            "customer": customer_id,
            "parent": {"subscription_details": {"subscription": subscription_id}},
        }},
    }
    _mock_event(monkeypatch, event)
    with TestClient(app) as client:
        first = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "mock-signature"})
        second = client.post("/webhooks/stripe", content=b"{}", headers={"stripe-signature": "mock-signature"})
    assert first.status_code == 200
    assert first.json()["matched"] is True
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
