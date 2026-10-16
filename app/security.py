import secrets
from pwdlib import PasswordHash
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from app.config import get_settings

_password_hash = PasswordHash.recommended()


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _password_hash.verify(password, password_hash)
    except (ValueError, TypeError):
        return False


def csrf_token(request) -> str:
    token = request.session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["_csrf"] = token
    return token


def verify_csrf(request, supplied: str | None) -> bool:
    expected = request.session.get("_csrf", "")
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


def token_hash(token: str) -> str:
    import hashlib
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def submission_serializer():
    return URLSafeTimedSerializer(get_settings().secret_key, salt="public-document-submission")


def make_submission_token(link_id: str) -> str:
    return submission_serializer().dumps({"link_id": link_id})


def read_submission_token(token: str, max_age: int = 60 * 60 * 24 * 30) -> str | None:
    try:
        data = submission_serializer().loads(token, max_age=max_age)
        value = data.get("link_id")
        return value if isinstance(value, str) else None
    except (BadSignature, SignatureExpired, TypeError, AttributeError):
        return None
