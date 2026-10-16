from app.validators import normalize_iban, safe_filename, validate_iban, validate_portuguese_nif


def test_valid_portuguese_nif_checksum():
    assert validate_portuguese_nif("501964843")
    assert validate_portuguese_nif(" 501 964 843 ")


def test_invalid_portuguese_nif_is_rejected():
    assert not validate_portuguese_nif("501964844")
    assert not validate_portuguese_nif("123")
    assert not validate_portuguese_nif("abcdefgh9")


def test_iban_checksum_and_normalization():
    iban = "PT50 0002 0123 1234 5678 9015 4"
    assert normalize_iban(iban) == "PT50000201231234567890154"
    assert validate_iban(iban)
    assert not validate_iban("PT50000201231234567890155")


def test_filename_path_traversal_is_removed():
    assert safe_filename("../../secret.pdf") == "secret.pdf"
    assert "/" not in safe_filename(r"..\secret.pdf")
