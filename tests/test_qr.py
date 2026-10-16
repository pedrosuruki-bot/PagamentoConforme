from io import BytesIO
from datetime import date

import fitz
import numpy as np
import zxingcpp
from PIL import Image

from app.services.documents import extract_portuguese_invoice_qr, parse_portuguese_invoice_qr

PAYLOAD = (
    "A:501964843*B:501964843*C:PT*D:FT*E:N*F:20261015*"
    "G:FT ABC/123*H:TESTE123-123*I1:PT*I7:100.00*I8:23.00*"
    "N:23.00*O:123.00*Q:ABCD*R:9999"
)


def test_parse_portuguese_invoice_qr_fields_without_claiming_authenticity():
    result = parse_portuguese_invoice_qr(PAYLOAD)
    assert result["issuer_nif"] == "501964843"
    assert result["customer_nif"] == "501964843"
    assert result["document_type"] == "FT"
    assert result["document_identifier"] == "FT ABC/123"
    assert result["atcud"] == "TESTE123-123"
    assert result["issue_date"] == "2026-10-15"
    assert result["total_amount"] == "123.00"
    assert result["tax_total"] == "23.00"
    assert result["requires_human_review"] is True


def test_extract_qr_from_pdf_returns_parsed_record():
    barcode = zxingcpp.create_barcode(PAYLOAD, zxingcpp.BarcodeFormat.QRCode, ec_level="50%")
    rendered = barcode.to_image(scale=6)
    png_array = np.asarray(rendered)
    image = Image.fromarray(png_array)
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")

    pdf = fitz.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(fitz.Rect(72, 72, 360, 360), stream=image_bytes.getvalue())
    pdf_bytes = pdf.tobytes()
    pdf.close()

    result = extract_portuguese_invoice_qr(pdf_bytes, "application/pdf")
    assert result["status"] == "decoded_for_review"
    assert result["records"][0]["issuer_nif"] == "501964843"
    assert result["records"][0]["total_amount"] == "123.00"
    assert "não confirma a autenticidade" in result["warnings"][0]
