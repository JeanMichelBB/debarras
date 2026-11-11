from types import SimpleNamespace

import auth
from conftest import CRED_ID


def test_register_begin_requires_discoverable_passkey(client):
    r = client.post("/auth/register/begin", json={})
    assert r.status_code == 200
    opts = r.json()["options"]
    assert opts["rp"]["id"] == "localhost"
    assert opts["authenticatorSelection"]["residentKey"] == "required"
    assert opts["challenge"]
    assert r.json()["state"]


def test_register_finish_creates_account_and_recovery_codes(client, register):
    headers, codes = register()
    assert len(codes) == 8 and len(set(codes)) == 8
    assert all(len(c.replace("-", "")) == 16 for c in codes)
    me = client.get("/me", headers=headers).json()
    assert me["passkeys"] == 1 and me["recovery_codes_left"] == 8
    assert me["lang"] == "en" and me["region"] == "CA"  # defaults


def test_register_finish_rejects_failed_verification(client, monkeypatch):
    def boom(**kw):
        raise ValueError("bad attestation")

    monkeypatch.setattr(auth, "verify_registration_response", boom)
    begin = client.post("/auth/register/begin", json={}).json()
    r = client.post("/auth/register/finish", json={"credential": {"id": "x"}, "state": begin["state"]})
    assert r.status_code == 400


def test_state_token_cannot_be_used_for_the_wrong_step(client):
    login_state = client.post("/auth/login/begin").json()["state"]
    r = client.post("/auth/register/finish", json={"credential": {"id": "x"}, "state": login_state})
    assert r.status_code == 400


def test_state_token_is_not_an_access_token(client):
    state = client.post("/auth/login/begin").json()["state"]
    assert client.get("/me", headers={"Authorization": f"Bearer {state}"}).status_code == 401


def test_login_with_registered_passkey(client, register, monkeypatch):
    headers, _ = register()
    monkeypatch.setattr(auth, "verify_authentication_response", lambda **kw: SimpleNamespace(new_sign_count=5))
    begin = client.post("/auth/login/begin").json()
    r = client.post("/auth/login/finish", json={"credential": {"id": CRED_ID}, "state": begin["state"]})
    assert r.status_code == 200
    me = client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"})
    assert me.status_code == 200


def test_login_with_unknown_passkey_fails(client):
    begin = client.post("/auth/login/begin").json()
    r = client.post("/auth/login/finish", json={"credential": {"id": "nope"}, "state": begin["state"]})
    assert r.status_code == 401


def test_login_failed_verification_fails(client, register, monkeypatch):
    register()

    def boom(**kw):
        raise ValueError("bad signature")

    monkeypatch.setattr(auth, "verify_authentication_response", boom)
    begin = client.post("/auth/login/begin").json()
    r = client.post("/auth/login/finish", json={"credential": {"id": CRED_ID}, "state": begin["state"]})
    assert r.status_code == 401


def test_recovery_code_works_once_and_is_normalized(client, register):
    headers, codes = register()
    code = codes[0]
    messy = code.lower().replace("-", " ")
    r = client.post("/auth/recover", json={"code": messy})
    assert r.status_code == 200
    assert client.get("/me", headers={"Authorization": f"Bearer {r.json()['access_token']}"}).status_code == 200
    again = client.post("/auth/recover", json={"code": code})
    assert again.status_code == 401
    assert client.get("/me", headers=headers).json()["recovery_codes_left"] == 7


def test_wrong_recovery_code_fails(client, register):
    register()
    assert client.post("/auth/recover", json={"code": "AAAA-BBBB-CCCC-DDDD"}).status_code == 401


def test_recovery_is_rate_limited(client):
    statuses = [client.post("/auth/recover", json={"code": "AAAA-BBBB-CCCC-DDDD"}).status_code for _ in range(10)]
    assert statuses[:8] == [401] * 8
    assert 429 in statuses[8:]


def test_regenerate_recovery_codes_invalidates_old(client, register):
    headers, old = register()
    new = client.post("/me/recovery-codes", headers=headers).json()["recovery_codes"]
    assert len(new) == 8 and not set(new) & set(old)
    assert client.post("/auth/recover", json={"code": old[0]}).status_code == 401
    assert client.post("/auth/recover", json={"code": new[0]}).status_code == 200


def test_update_settings(client, user):
    r = client.patch("/me", headers=user, json={"lang": "fr", "region": "fr"})
    assert r.status_code == 200 and r.json()["lang"] == "fr" and r.json()["region"] == "FR"
    assert client.patch("/me", headers=user, json={"lang": "de"}).status_code == 422
    assert client.patch("/me", headers=user, json={"region": "CAN"}).status_code == 422


def test_cannot_remove_only_passkey(client, user):
    pk = client.get("/me/passkeys", headers=user).json()[0]
    assert client.delete(f"/me/passkeys/{pk['id']}", headers=user).status_code == 409


def test_add_second_passkey_then_remove_one(client, user, monkeypatch):
    begin = client.post("/me/passkeys/begin", headers=user).json()
    assert begin["options"]["excludeCredentials"]  # existing passkey is excluded
    monkeypatch.setattr(auth, "verify_registration_response", lambda **kw: SimpleNamespace(
        credential_id=b"cred-two", credential_public_key=b"pk2", sign_count=0))
    r = client.post("/me/passkeys/finish", headers=user, json={"credential": {"id": "y"}, "state": begin["state"]})
    assert r.status_code == 201 and r.json()["passkeys"] == 2
    first = client.get("/me/passkeys", headers=user).json()[0]
    assert client.delete(f"/me/passkeys/{first['id']}", headers=user).status_code == 204


def test_delete_account_removes_everything(client, register):
    headers, codes = register()
    client.post("/swipe", headers=headers, json={"media_type": "movie", "tmdb_id": 1, "status": "watched"})
    assert client.delete("/me", headers=headers).status_code == 204
    assert client.get("/me", headers=headers).status_code == 401
    assert client.post("/auth/recover", json={"code": codes[0]}).status_code == 401

    from database.connection import SessionLocal
    from database.models import Passkey, RecoveryCode, User, UserTitle

    db = SessionLocal()
    try:
        for model in (User, Passkey, RecoveryCode, UserTitle):
            assert db.query(model).count() == 0
    finally:
        db.close()


def test_requests_need_auth(client):
    for path in ("/me", "/titles/queue", "/swipes", "/swipes/stats", "/export/watched", "/meta/genres"):
        assert client.get(path).status_code == 401, path
