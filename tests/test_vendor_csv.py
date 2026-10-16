import pytest

from app.services.vendor_csv import VendorCSVError, parse_subcontractor_csv


VALID_NIF = "501964843"
VALID_IBAN = "PT50000201231234567890154"


def test_csv_preview_normalizes_headers_and_data_without_inserting():
    content = (
        "nome,nif,email,telefone,iban,notas\n"
        f"Fornecedor Um,{VALID_NIF},FIN@EXEMPLO.PT,123,{VALID_IBAN},Teste\n"
    ).encode("utf-8-sig")
    rows = parse_subcontractor_csv(content, existing_nifs=set())
    assert len(rows) == 1
    assert rows[0]["valid"] is True
    assert rows[0]["name"] == "Fornecedor Um"
    assert rows[0]["email"] == "fin@exemplo.pt"
    assert rows[0]["iban"] == VALID_IBAN
    assert rows[0]["notes"] == "Teste"


def test_duplicate_nif_within_csv_is_flagged_on_later_row():
    content = (
        "name,nif\n"
        f"Fornecedor Um,{VALID_NIF}\n"
        f"Fornecedor Dois,{VALID_NIF}\n"
    ).encode()
    rows = parse_subcontractor_csv(content, existing_nifs=set())
    assert rows[0]["valid"] is True
    assert rows[1]["valid"] is False
    assert "NIF duplicado neste ficheiro." in rows[1]["errors"]


def test_existing_nif_and_bad_iban_are_flagged():
    content = f"name,nif,iban\nFornecedor,{VALID_NIF},PT0000000000000000000000000\n".encode()
    rows = parse_subcontractor_csv(content, existing_nifs={VALID_NIF})
    assert not rows[0]["valid"]
    assert "NIF já registado nesta empresa." in rows[0]["errors"]
    assert "IBAN inválido." in rows[0]["errors"]


@pytest.mark.parametrize("content, message", [
    (b"", "vazio"),
    (b"\xff\xfe\x00", "UTF-8"),
    (b"email,nif\nx@y.pt,123456789\n", "name"),
])
def test_invalid_csv_is_rejected(content, message):
    with pytest.raises(VendorCSVError, match=message):
        parse_subcontractor_csv(content, existing_nifs=set())
