from app.security import hash_password, verify_password, make_submission_token, read_submission_token


def test_password_hash_does_not_store_plaintext():
    password = "correct-horse-battery-staple-92"
    hashed = hash_password(password)
    assert password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("wrong-password", hashed)


def test_signed_submission_token_round_trip():
    token = make_submission_token("123")
    assert read_submission_token(token) == "123"
    assert read_submission_token(token + "bad") is None
