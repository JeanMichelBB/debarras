"""Passkey-only authentication (WebAuthn). No email, no phone, no password.

Identity is a random handle. Sign-up creates the account and returns one-time recovery
codes; a recovery code logs in when every passkey is lost, then the user adds a new passkey.
WebAuthn challenges travel in short-lived signed "state" tokens, so the server keeps no
challenge state.
"""

import base64
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

import config
from database.connection import get_db
from database.models import (
    ImportJob,
    Passkey,
    RecoveryCode,
    User,
    UserTitle,
    utcnow,
)
from ratelimit import rate_limit

router = APIRouter(tags=["auth"])
bearer = HTTPBearer(auto_error=False)
auth_limit = rate_limit("auth", 20, 60)
recover_limit = rate_limit("recover", 8, 600)

STATE_MINUTES = 5
RECOVERY_CODE_COUNT = 8


# ── tokens ────────────────────────────────────────────────────────────────────
def _secret() -> str:
    if not config.JWT_SECRET:
        raise HTTPException(500, "server misconfigured: JWT_SECRET not set")
    return config.JWT_SECRET


def create_token(user_id: int) -> str:
    exp = datetime.now(timezone.utc) + timedelta(days=config.JWT_EXPIRE_DAYS)
    return jwt.encode({"typ": "access", "sub": str(user_id), "exp": exp}, _secret(), algorithm="HS256")


def _make_state(purpose: str, challenge: bytes, **extra) -> str:
    exp = datetime.now(timezone.utc) + timedelta(minutes=STATE_MINUTES)
    payload = {"typ": "state", "purpose": purpose, "challenge": bytes_to_base64url(challenge), "exp": exp, **extra}
    return jwt.encode(payload, _secret(), algorithm="HS256")


def _read_state(state: str, purpose: str) -> dict:
    try:
        payload = jwt.decode(state, _secret(), algorithms=["HS256"])
    except jwt.PyJWTError:
        raise HTTPException(400, "sign-in session expired, try again")
    if payload.get("typ") != "state" or payload.get("purpose") != purpose:
        raise HTTPException(400, "invalid sign-in session")
    return payload


def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer),
    db: Session = Depends(get_db),
) -> User:
    if creds is None:
        raise HTTPException(401, "not authenticated")
    try:
        payload = jwt.decode(creds.credentials, _secret(), algorithms=["HS256"])
        if payload.get("typ") != "access":
            raise ValueError("wrong token type")
        user = db.get(User, int(payload["sub"]))
    except (jwt.PyJWTError, KeyError, ValueError):
        raise HTTPException(401, "invalid token")
    if user is None:
        raise HTTPException(401, "invalid token")
    return user


# ── recovery codes ────────────────────────────────────────────────────────────
def _normalize_code(code: str) -> str:
    return "".join(ch for ch in code.upper() if ch.isalnum())


def _hash_code(code: str) -> str:
    return hmac.new(_secret().encode(), _normalize_code(code).encode(), hashlib.sha256).hexdigest()


def create_recovery_codes(db: Session, user: User) -> list[str]:
    """Replace the user's unused codes with a fresh set. Returns the plaintext codes (shown once)."""
    db.query(RecoveryCode).filter(RecoveryCode.user_id == user.id).delete()
    codes = []
    for _ in range(RECOVERY_CODE_COUNT):
        raw = base64.b32encode(secrets.token_bytes(10)).decode().rstrip("=")  # 16 chars, 80 bits
        codes.append("-".join(raw[i:i + 4] for i in range(0, 16, 4)))
    for c in codes:
        db.add(RecoveryCode(user_id=user.id, code_hash=_hash_code(c)))
    db.commit()
    return codes


# ── schemas ───────────────────────────────────────────────────────────────────
class RegisterBegin(BaseModel):
    display_name: str | None = Field(None, max_length=40)


class FinishBody(BaseModel):
    credential: dict
    state: str
    name: str | None = Field(None, max_length=60)


class RecoverBody(BaseModel):
    code: str = Field(min_length=8, max_length=40)


class MeUpdate(BaseModel):
    lang: str | None = Field(None, pattern="^(en|fr)$")
    region: str | None = Field(None, pattern="^[A-Za-z]{2}$")
    display_name: str | None = Field(None, max_length=40)


def _selection() -> AuthenticatorSelectionCriteria:
    # Discoverable credentials so sign-in needs no username.
    return AuthenticatorSelectionCriteria(
        resident_key=ResidentKeyRequirement.REQUIRED,
        user_verification=UserVerificationRequirement.PREFERRED,
    )


def _options_dict(options) -> dict:
    return json.loads(options_to_json(options))


# ── sign-up ───────────────────────────────────────────────────────────────────
@router.post("/auth/register/begin", dependencies=[Depends(auth_limit)])
def register_begin(body: RegisterBegin | None = None):
    handle = secrets.token_hex(16)
    name = (body.display_name if body and body.display_name else None) or "Débarras"
    options = generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name=config.WEBAUTHN_RP_NAME,
        user_id=handle.encode(),
        user_name=name,
        user_display_name=name,
        authenticator_selection=_selection(),
    )
    return {
        "options": _options_dict(options),
        "state": _make_state("register", options.challenge, handle=handle, display_name=name),
    }


@router.post("/auth/register/finish", status_code=201, dependencies=[Depends(auth_limit)])
def register_finish(body: FinishBody, db: Session = Depends(get_db)):
    st = _read_state(body.state, "register")
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=base64url_to_bytes(st["challenge"]),
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGINS,
        )
    except Exception:
        raise HTTPException(400, "passkey verification failed")

    cred_id = bytes_to_base64url(verified.credential_id)
    if db.scalar(select(Passkey).where(Passkey.credential_id == cred_id)):
        raise HTTPException(409, "this passkey is already registered")
    name = st.get("display_name")
    user = User(handle=st["handle"], display_name=None if name == "Débarras" else name)
    db.add(user)
    db.flush()
    db.add(Passkey(
        user_id=user.id, credential_id=cred_id, public_key=verified.credential_public_key,
        sign_count=verified.sign_count, name=body.name,
    ))
    db.commit()
    codes = create_recovery_codes(db, user)
    return {"access_token": create_token(user.id), "token_type": "bearer", "recovery_codes": codes}


# ── sign-in ───────────────────────────────────────────────────────────────────
@router.post("/auth/login/begin", dependencies=[Depends(auth_limit)])
def login_begin():
    options = generate_authentication_options(
        rp_id=config.WEBAUTHN_RP_ID,
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    return {"options": _options_dict(options), "state": _make_state("login", options.challenge)}


@router.post("/auth/login/finish", dependencies=[Depends(auth_limit)])
def login_finish(body: FinishBody, db: Session = Depends(get_db)):
    st = _read_state(body.state, "login")
    cred_id = body.credential.get("id")
    pk = db.scalar(select(Passkey).where(Passkey.credential_id == cred_id)) if cred_id else None
    if pk is None:
        raise HTTPException(401, "unknown passkey")
    try:
        verified = verify_authentication_response(
            credential=body.credential,
            expected_challenge=base64url_to_bytes(st["challenge"]),
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGINS,
            credential_public_key=pk.public_key,
            credential_current_sign_count=pk.sign_count,
        )
    except Exception:
        raise HTTPException(401, "passkey verification failed")
    pk.sign_count = verified.new_sign_count
    db.commit()
    return {"access_token": create_token(pk.user_id), "token_type": "bearer"}


@router.post("/auth/recover", dependencies=[Depends(recover_limit)])
def recover(body: RecoverBody, db: Session = Depends(get_db)):
    rc = db.scalar(select(RecoveryCode).where(
        RecoveryCode.code_hash == _hash_code(body.code), RecoveryCode.used_at.is_(None)
    ))
    if rc is None:
        raise HTTPException(401, "invalid or already used recovery code")
    rc.used_at = utcnow()
    db.commit()
    # The client should now prompt the user to add a new passkey.
    return {"access_token": create_token(rc.user_id), "token_type": "bearer"}


# ── account ───────────────────────────────────────────────────────────────────
def _me(db: Session, user: User) -> dict:
    n_pk = db.scalar(select(func.count()).select_from(Passkey).where(Passkey.user_id == user.id))
    n_rc = db.scalar(select(func.count()).select_from(RecoveryCode).where(
        RecoveryCode.user_id == user.id, RecoveryCode.used_at.is_(None)))
    return {
        "id": user.id, "display_name": user.display_name, "lang": user.lang, "region": user.region,
        "passkeys": n_pk, "recovery_codes_left": n_rc, "created_at": user.created_at.isoformat(),
    }


@router.get("/me")
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _me(db, user)


@router.patch("/me")
def update_me(body: MeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if body.lang is not None:
        user.lang = body.lang
    if body.region is not None:
        user.region = body.region.upper()
    if body.display_name is not None:
        user.display_name = body.display_name or None
    db.commit()
    return _me(db, user)


@router.post("/me/recovery-codes")
def regenerate_recovery_codes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Replaces all unused codes. The new codes are shown once."""
    return {"recovery_codes": create_recovery_codes(db, user)}


@router.get("/me/passkeys")
def list_passkeys(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Passkey).where(Passkey.user_id == user.id).order_by(Passkey.id)).all()
    return [{"id": p.id, "name": p.name, "created_at": p.created_at.isoformat()} for p in rows]


@router.post("/me/passkeys/begin")
def add_passkey_begin(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    existing = db.scalars(select(Passkey).where(Passkey.user_id == user.id)).all()
    options = generate_registration_options(
        rp_id=config.WEBAUTHN_RP_ID,
        rp_name=config.WEBAUTHN_RP_NAME,
        user_id=user.handle.encode(),
        user_name=user.display_name or "Débarras",
        user_display_name=user.display_name or "Débarras",
        authenticator_selection=_selection(),
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=base64url_to_bytes(p.credential_id)) for p in existing
        ],
    )
    return {"options": _options_dict(options), "state": _make_state("add", options.challenge, uid=user.id)}


@router.post("/me/passkeys/finish", status_code=201)
def add_passkey_finish(body: FinishBody, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    st = _read_state(body.state, "add")
    if st.get("uid") != user.id:
        raise HTTPException(400, "invalid sign-in session")
    try:
        verified = verify_registration_response(
            credential=body.credential,
            expected_challenge=base64url_to_bytes(st["challenge"]),
            expected_rp_id=config.WEBAUTHN_RP_ID,
            expected_origin=config.WEBAUTHN_ORIGINS,
        )
    except Exception:
        raise HTTPException(400, "passkey verification failed")
    cred_id = bytes_to_base64url(verified.credential_id)
    if db.scalar(select(Passkey).where(Passkey.credential_id == cred_id)):
        raise HTTPException(409, "this passkey is already registered")
    db.add(Passkey(
        user_id=user.id, credential_id=cred_id, public_key=verified.credential_public_key,
        sign_count=verified.sign_count, name=body.name,
    ))
    db.commit()
    return _me(db, user)


@router.delete("/me/passkeys/{passkey_id}", status_code=204)
def delete_passkey(passkey_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(Passkey).where(Passkey.user_id == user.id)).all()
    target = next((p for p in rows if p.id == passkey_id), None)
    if target is None:
        raise HTTPException(404, "passkey not found")
    if len(rows) <= 1:
        raise HTTPException(409, "cannot remove your only passkey")
    db.delete(target)
    db.commit()


@router.delete("/me", status_code=204)
def delete_account(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Account deletion (Law 25 / GDPR): removes the user and everything tied to them."""
    for model in (UserTitle, Passkey, RecoveryCode, ImportJob):
        db.query(model).filter(model.user_id == user.id).delete()
    db.delete(user)
    db.commit()
