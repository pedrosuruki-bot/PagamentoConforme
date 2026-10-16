from datetime import date

from app.services.document_reminders import days_until_expiry, reminder_stage


def test_reminder_thresholds_are_stable_and_ordered():
    assert reminder_stage(45) is None
    assert reminder_stage(30) == ("document_expiring", "30d")
    assert reminder_stage(20) == ("document_expiring", "30d")
    assert reminder_stage(15) == ("document_expiring", "15d")
    assert reminder_stage(8) == ("document_expiring", "15d")
    assert reminder_stage(7) == ("document_expiring", "7d")
    assert reminder_stage(1) == ("document_expiring", "7d")
    assert reminder_stage(0) == ("document_expiring", "7d")
    assert reminder_stage(-1) == ("document_expired", "expired")


def test_days_until_expiry_uses_calendar_dates():
    assert days_until_expiry(date(2026, 10, 20), date(2026, 10, 16)) == 4
    assert days_until_expiry(None, date(2026, 10, 16)) is None
