import fitz
from app.services.documents import detect_file_type, extract_pdf_text, suggest_invoice_fields


def make_pdf(text: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text)
    content = doc.tobytes()
    doc.close()
    return content


def test_pdf_text_extraction_and_invoice_suggestions():
    pdf = make_pdf("Fatura FT2026/12\nData 2026-10-15\nTotal 123,45")
    extracted, status = extract_pdf_text(pdf)
    assert status == "text_extracted"
    assert "Fatura" in extracted
    suggestions = suggest_invoice_fields(extracted)
    assert suggestions["issue_date"] == "2026-10-15"
    assert suggestions["requires_human_review"] is True


def test_magic_bytes_are_used_for_file_detection():
    assert detect_file_type(b"%PDF-1.7 test") == "application/pdf"
    assert detect_file_type(b"\x89PNG\r\n\x1a\nrest") == "image/png"
    assert detect_file_type(b"\xff\xd8\xffrest") == "image/jpeg"
    assert detect_file_type(b"not really a PDF") is None
