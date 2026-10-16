from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")
EXPIRY_WARNING_DAYS = 30


def lisbon_today() -> date:
    return datetime.now(LISBON).date()


def document_expiry_state(expires_on: date | datetime | None, today: date | None = None,
                          status: str = "review_required") -> dict:
    """Return a date-based alert and human-review state, never a legal authenticity verdict."""
    current_date = today or lisbon_today()
    expiry_date = expires_on.date() if isinstance(expires_on, datetime) else expires_on

    if expiry_date is not None and expiry_date < current_date:
        return {"state": "expired", "label": "Data de validade ultrapassada", "severity": "bad"}
    if expiry_date is not None and expiry_date <= current_date + timedelta(days=EXPIRY_WARNING_DAYS):
        return {"state": "expiring_soon", "label": "Data de validade próxima", "severity": "warn"}
    if status == "invalid":
        return {"state": "invalid", "label": "Documento rejeitado", "severity": "bad"}
    if status == "reviewed_by_human":
        if expiry_date is None:
            return {
                "state": "reviewed_by_human",
                "label": "Revisão registada; validade não confirmada",
                "severity": "warn",
            }
        return {"state": "reviewed_by_human", "label": "Revisão humana registada", "severity": "ok"}
    if expiry_date is None:
        return {"state": "review_required", "label": "Validade não confirmada", "severity": "warn"}
    return {"state": "review_required", "label": "Conteúdo por rever", "severity": "warn"}
