from datetime import date
from decimal import Decimal
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

from app.validators import normalize_iban, validate_iban

NS = "urn:iso:std:iso:20022:tech:xsd:pain.001.001.03"


def _el(parent, tag, text=None):
    node = SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        node.text = str(text)
    return node


def build_pain001(*, message_id: str, company_name: str, debtor_iban: str,
                  execution_date: date, transactions: list[dict], creditor_bic: str = "") -> str:
    """Create a pain.001.001.03 draft. Bank acceptance must be verified per bank profile."""
    if not company_name.strip():
        raise ValueError("O nome da empresa ordenante é obrigatório.")
    debtor_iban = normalize_iban(debtor_iban)
    if not validate_iban(debtor_iban):
        raise ValueError("O IBAN da conta ordenante não é válido.")
    if not transactions:
        raise ValueError("O lote não contém pagamentos.")
    total = Decimal("0.00")
    cleaned = []
    for tx in transactions:
        name = str(tx.get("creditor_name", "")).strip()
        iban = normalize_iban(str(tx.get("creditor_iban", "")))
        amount = Decimal(str(tx.get("amount", "0"))).quantize(Decimal("0.01"))
        reference = str(tx.get("reference", "")).strip()[:140]
        if not name or not validate_iban(iban) or amount <= 0:
            raise ValueError("Existe um beneficiário, IBAN ou montante inválido.")
        total += amount
        cleaned.append({"name": name, "iban": iban, "amount": amount, "reference": reference})

    root = Element(f"{{{NS}}}Document")
    init = _el(root, "CstmrCdtTrfInitn")
    group = _el(init, "GrpHdr")
    _el(group, "MsgId", message_id[:35])
    from datetime import datetime, timezone
    _el(group, "CreDtTm", datetime.now(timezone.utc).replace(microsecond=0).isoformat())
    _el(group, "NbOfTxs", len(cleaned))
    _el(group, "CtrlSum", f"{total:.2f}")
    init_party = _el(group, "InitgPty")
    _el(init_party, "Nm", company_name[:140])

    pmt = _el(init, "PmtInf")
    _el(pmt, "PmtInfId", message_id[:35])
    _el(pmt, "PmtMtd", "TRF")
    _el(pmt, "BtchBookg", "true")
    _el(pmt, "NbOfTxs", len(cleaned))
    _el(pmt, "CtrlSum", f"{total:.2f}")
    pmt_type = _el(pmt, "PmtTpInf")
    _el(pmt_type, "SvcLvl")
    pmt.find(f"{{{NS}}}PmtTpInf").find(f"{{{NS}}}SvcLvl").append(Element(f"{{{NS}}}Cd"))
    pmt.find(f"{{{NS}}}PmtTpInf").find(f"{{{NS}}}SvcLvl").find(f"{{{NS}}}Cd").text = "SEPA"
    _el(pmt, "ReqdExctnDt", execution_date.isoformat())
    debtor = _el(pmt, "Dbtr")
    _el(debtor, "Nm", company_name[:140])
    debtor_acct = _el(pmt, "DbtrAcct")
    debtor_id = _el(debtor_acct, "Id")
    _el(debtor_id, "IBAN", debtor_iban)
    debtor_agent = _el(pmt, "DbtrAgt")
    debtor_fin = _el(debtor_agent, "FinInstnId")
    if creditor_bic.strip():
        _el(debtor_fin, "BIC", creditor_bic.strip().upper()[:11])
    else:
        other = _el(debtor_fin, "Othr")
        _el(other, "Id", "NOTPROVIDED")
    _el(pmt, "ChrgBr", "SLEV")

    for index, tx in enumerate(cleaned, start=1):
        item = _el(pmt, "CdtTrfTxInf")
        payment_id = _el(item, "PmtId")
        _el(payment_id, "InstrId", f"{message_id[:20]}-{index}")
        _el(payment_id, "EndToEndId", (tx["reference"] or f"PC-{message_id}-{index}")[:35])
        amount = _el(item, "Amt")
        _el(amount, "InstdAmt", f"{tx['amount']:.2f}").set("Ccy", "EUR")
        agent = _el(item, "CdtrAgt")
        agent_fin = _el(agent, "FinInstnId")
        other = _el(agent_fin, "Othr")
        _el(other, "Id", "NOTPROVIDED")
        payee = _el(item, "Cdtr")
        _el(payee, "Nm", tx["name"][:140])
        payee_acct = _el(item, "CdtrAcct")
        payee_id = _el(payee_acct, "Id")
        _el(payee_id, "IBAN", tx["iban"])
        remittance = _el(item, "RmtInf")
        _el(remittance, "Ustrd", (tx["reference"] or "Pagamento de fatura")[:140])

    raw = tostring(root, encoding="utf-8", xml_declaration=True)
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8").decode("utf-8")


def validate_draft_xml(xml_content: str) -> list[str]:
    """Basic local checks only. Not a replacement for the applicable XSD or bank certification."""
    errors = []
    try:
        from lxml import etree
        root = etree.fromstring(xml_content.encode("utf-8"))
    except Exception:
        return ["XML malformado."]
    if root.tag != f"{{{NS}}}Document":
        errors.append("A raiz XML não corresponde a pain.001.001.03.")
    required = [
        f".//{{{NS}}}MsgId",
        f".//{{{NS}}}NbOfTxs",
        f".//{{{NS}}}CtrlSum",
        f".//{{{NS}}}DbtrAcct/{{{NS}}}Id/{{{NS}}}IBAN",
    ]
    for path in required:
        if root.find(path) is None or not (root.find(path).text or "").strip():
            errors.append(f"Campo obrigatório ausente: {path.rsplit('}', 1)[-1]}.")
    return errors
