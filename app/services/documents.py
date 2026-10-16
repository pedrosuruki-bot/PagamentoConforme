import re
from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

import fitz


def extract_pdf_text(content: bytes, max_chars: int = 60000) -> tuple[str, str]:
    """Extract text only; this is not authentication or legal validation of the document."""
    try:
        with fitz.open(stream=content, filetype="pdf") as pdf:
            if pdf.is_encrypted:
                return "", "pdf_encrypted"
            parts = []
            for page in pdf:
                parts.append(page.get_text("text"))
                if sum(map(len, parts)) >= max_chars:
                    break
            text = "\n".join(parts)[:max_chars].strip()
            return text, "text_extracted" if text else "no_readable_text"
    except Exception:
        return "", "pdf_unreadable"


def suggest_invoice_fields(text: str) -> dict:
    """Best-effort suggestions; every value must be reviewed by a person."""
    result: dict = {}
    if not text:
        return result
    date_match = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", text)
    if date_match:
        try:
            result["issue_date"] = date.fromisoformat(date_match.group(1)).isoformat()
        except ValueError:
            pass
    number_match = re.search(r"(?i)\b(?:fatura|factura|invoice)\s*(?:n[.ºo°]*\s*)?[:#-]?\s*([A-Z0-9./_-]{2,30})", text)
    if number_match:
        result["number"] = number_match.group(1).strip()
    amount_matches = re.findall(r"(?<!\d)(\d{1,3}(?:[ .]\d{3})*[,.]\d{2})(?!\d)", text)
    if amount_matches:
        candidates = []
        for raw in amount_matches:
            normalized = raw.replace(" ", "").replace(".", "").replace(",", ".")
            try:
                candidates.append(Decimal(normalized))
            except InvalidOperation:
                continue
        if candidates:
            result["possible_amounts"] = [str(v.quantize(Decimal("0.01"))) for v in candidates[-5:]]
    result["requires_human_review"] = True
    return result


def detect_file_type(content: bytes) -> str | None:
    if content.startswith(b"%PDF-"):
        return "application/pdf"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    return None
