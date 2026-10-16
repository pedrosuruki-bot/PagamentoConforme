from datetime import date, datetime
from app.services.document_status import document_expiry_state


TODAY = date(2026, 10, 16)


def test_missing_expiry_needs_review():
    assert document_expiry_state(None, TODAY)["state"] == "review_required"
    assert document_expiry_state(None, TODAY)["label"] == "Validade não confirmada"


def test_expired_date_is_flagged():
    result = document_expiry_state(date(2026, 10, 15), TODAY)
    assert result["state"] == "expired"
    assert result["severity"] == "bad"


def test_expiry_within_thirty_days_is_flagged():
    result = document_expiry_state(datetime(2026, 11, 15), TODAY)
    assert result["state"] == "expiring_soon"
    assert result["severity"] == "warn"


def test_future_expiry_does_not_mark_document_legally_valid():
    result = document_expiry_state(date(2027, 1, 1), TODAY)
    assert result["state"] == "review_required"
    assert result["label"] == "Conteúdo por rever"



def test_human_review_status_is_displayed_without_claiming_official_validity():
    result = document_expiry_state(date(2027, 1, 1), TODAY, "reviewed_by_human")
    assert result["state"] == "reviewed_by_human"
    assert result["label"] == "Revisão humana registada"
    assert result["severity"] == "ok"


def test_expired_document_remains_expired_even_if_user_reviewed_it():
    result = document_expiry_state(date(2026, 10, 15), TODAY, "reviewed_by_human")
    assert result["state"] == "expired"
