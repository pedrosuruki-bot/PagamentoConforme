from datetime import date


def reminder_stage(days_until_expiry: int) -> tuple[str, str] | None:
    """Return a stable notification type/period key for the current expiry window."""
    if days_until_expiry < 0:
        return ("document_expired", "expired")
    if days_until_expiry <= 7:
        return ("document_expiring", "7d")
    if days_until_expiry <= 15:
        return ("document_expiring", "15d")
    if days_until_expiry <= 30:
        return ("document_expiring", "30d")
    return None


def days_until_expiry(expires_on: date | None, today: date) -> int | None:
    if expires_on is None:
        return None
    return (expires_on - today).days
