from datetime import date
import pytest
from app.services.sepa import build_pain001, validate_draft_xml

DEBTOR = "PT50000201231234567890154"
CREDITOR = "PT50000201231234567890154"


def sample_xml():
    return build_pain001(
        message_id="PC-TEST-0001",
        company_name="Empresa de Teste Lda",
        debtor_iban=DEBTOR,
        execution_date=date(2026, 10, 20),
        transactions=[{
            "creditor_name": "Fornecedor de Teste Lda",
            "creditor_iban": CREDITOR,
            "amount": "123.45",
            "reference": "FT TESTE/2026/1",
        }],
    )


def test_sepa_draft_contains_required_fields_and_valid_xml():
    xml = sample_xml()
    assert "pain.001.001.03" in xml
    assert "123.45" in xml
    assert "Fornecedor de Teste Lda" in xml
    assert validate_draft_xml(xml) == []


def test_sepa_rejects_invalid_debtor_iban():
    with pytest.raises(ValueError, match="IBAN"):
        build_pain001(
            message_id="PC-TEST-0002",
            company_name="Empresa",
            debtor_iban="PT00-invalid",
            execution_date=date(2026, 10, 20),
            transactions=[{"creditor_name": "A", "creditor_iban": CREDITOR, "amount": "10", "reference": "FT1"}],
        )


def test_sepa_rejects_zero_amount():
    with pytest.raises(ValueError, match="beneficiário"):
        build_pain001(
            message_id="PC-TEST-0003",
            company_name="Empresa",
            debtor_iban=DEBTOR,
            execution_date=date(2026, 10, 20),
            transactions=[{"creditor_name": "A", "creditor_iban": CREDITOR, "amount": "0", "reference": "FT1"}],
        )


def test_local_validator_reports_malformed_xml():
    assert validate_draft_xml("<nope") == ["XML malformado."]
