import csv
import io

from app.validators import normalize_iban, normalize_nif, validate_iban, validate_portuguese_nif


ALIASES = {
    "name": "name",
    "nome": "name",
    "empresa": "name",
    "denominacao_social": "name",
    "nif": "nif",
    "vat": "nif",
    "email": "email",
    "e-mail": "email",
    "phone": "phone",
    "telefone": "phone",
    "telemovel": "phone",
    "iban": "iban",
    "notes": "notes",
    "notas": "notes",
}


class VendorCSVError(ValueError):
    """A user-correctable CSV import error."""


def parse_subcontractor_csv(content: bytes, existing_nifs: set[str],
                            max_bytes: int = 1_000_000, max_rows: int = 500) -> list[dict]:
    if not content:
        raise VendorCSVError("O ficheiro está vazio.")
    if len(content) > max_bytes:
        raise VendorCSVError("O ficheiro excede o limite de 1 MB.")
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise VendorCSVError("O CSV tem de estar codificado em UTF-8.") from exc

    reader = csv.DictReader(io.StringIO(csv_text))
    if not reader.fieldnames:
        raise VendorCSVError("Não foram encontrados cabeçalhos no CSV.")
    normalized_headers = [ALIASES.get(str(header or "").strip().lower()) for header in reader.fieldnames]
    if "name" not in normalized_headers:
        raise VendorCSVError("O CSV tem de conter uma coluna 'name' ou 'nome'.")

    seen_nifs: set[str] = set()
    rows = []
    for line_number, raw in enumerate(reader, start=2):
        if line_number > max_rows + 1:
            raise VendorCSVError(f"O CSV pode conter no máximo {max_rows} linhas de dados.")
        normalized = {}
        for header, value in (raw or {}).items():
            alias = ALIASES.get(str(header or "").strip().lower())
            if alias:
                normalized[alias] = str(value or "").strip()
        row = {
            "line": line_number,
            "name": normalized.get("name", "")[:180],
            "nif": normalize_nif(normalized.get("nif", "")),
            "email": normalized.get("email", "").lower()[:320],
            "phone": normalized.get("phone", "")[:40],
            "iban": normalize_iban(normalized.get("iban", "")),
            "notes": normalized.get("notes", "")[:2000],
            "valid": True,
            "errors": [],
        }
        if not row["name"]:
            row["errors"].append("Nome em falta.")
        if row["nif"] and not validate_portuguese_nif(row["nif"]):
            row["errors"].append("NIF inválido.")
        if row["iban"] and not validate_iban(row["iban"]):
            row["errors"].append("IBAN inválido.")
        if row["email"] and "@" not in row["email"]:
            row["errors"].append("Email inválido.")
        if row["nif"] and row["nif"] in existing_nifs:
            row["errors"].append("NIF já registado nesta empresa.")
        if row["nif"] and row["nif"] in seen_nifs:
            row["errors"].append("NIF duplicado neste ficheiro.")
        if row["nif"]:
            seen_nifs.add(row["nif"])
        row["valid"] = not row["errors"]
        rows.append(row)

    if not rows:
        raise VendorCSVError("O CSV não contém linhas de dados.")
    return rows
