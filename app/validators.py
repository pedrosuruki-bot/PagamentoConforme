import re


def validate_portuguese_nif(value: str) -> bool:
    """Check Portuguese NIF format and check digit; this does not verify tax status."""
    nif = re.sub(r"\s+", "", value or "")
    if not re.fullmatch(r"\d{9}", nif) or nif[0] not in "123456789":
        return False
    digits = [int(c) for c in nif]
    check = sum(digits[i] * (9 - i) for i in range(8))
    remainder = check % 11
    expected = 0 if remainder < 2 else 11 - remainder
    return digits[8] == expected


def validate_iban(value: str) -> bool:
    """Validate IBAN syntax and mod-97 checksum; does not confirm account ownership."""
    iban = re.sub(r"\s+", "", (value or "").upper())
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", iban):
        return False
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    remainder = 0
    for char in numeric:
        remainder = (remainder * 10 + int(char)) % 97
    return remainder == 1


def normalize_iban(value: str) -> str:
    return re.sub(r"\s+", "", (value or "").upper())


def normalize_nif(value: str) -> str:
    return re.sub(r"\s+", "", value or "")


def safe_filename(filename: str) -> str:
    name = (filename or "document.pdf").replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._")
    return (name or "document.pdf")[:120]
