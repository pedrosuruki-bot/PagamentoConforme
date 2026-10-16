from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LISBON = ZoneInfo("Europe/Lisbon")
EXPIRY_WARNING_DAYS = 30


def lisbon_today() -> date:
    return datetime.now(LISBON).date()


def document_expiry_state(expires_on: date | datetime | None, today: date | None = None) -> dict:
    """Return a date-based alert, never a legal authenticity verdict."""
    if expires_on is None:
        return {
            "state": "review_required",
            "label": "Validade não confirmada",
            "severity": "warn",
        }
    expiry_date = expires_on.date() if isinstance(expires_on, datetime) else expires_on
    current_date = today or lisbon_today()
    if expiry_date < current_date:
        return {
            "state": "expired",
            "label": "Data de validade ultrapassada",
            "severity": "bad",
        }
    if expiry_date <= current_date + timedelta(days=EXPIRY_WARNING_DAYS):
        return {
            "state": "expiring_soon",
            "label": "Data de validade próxima",
            "severity": "warn",
        }
    return {
        "state": "review_required",
        "label": "Conteúdo por rever",
        "severity": "warn",
    }
