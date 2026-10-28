"""Common Ground's small, auditable RFC 8785 / Ed25519 wire protocol.

Verification is deliberately stateless. A receiver MUST additionally persist nonces,
check its registered key/revocation set and compare consent revisions transactionally.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import rfc8785
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

BODY_KEYS = {"type", "schema_version", "message_id", "issuer", "audience", "circle_id", "issued_at", "expires_at", "nonce", "key_id", "consent_revision", "payload"}
MESSAGE_TYPES = {"ReleaseGrant", "Approval", "Withdrawal"}


def canonical(value: Any) -> bytes:
    try:
        return rfc8785.dumps(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("Value is not canonical JSON") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def expires_in(seconds: int | float) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="microseconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("Expected a UTC ISO timestamp ending in Z")
    try:
        result = datetime.fromisoformat(value[:-1] + "+00:00")
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if result.utcoffset() != timedelta(0):
        raise ValueError("Expected UTC timestamp")
    return result


def b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def b64decode(value: str) -> bytes:
    if not isinstance(value, str) or not value or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise ValueError("Invalid base64url")
    try:
        return base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("Invalid base64url") from exc


def _private(value: Any) -> Ed25519PrivateKey:
    if isinstance(value, Ed25519PrivateKey):
        return value
    try:
        return Ed25519PrivateKey.from_private_bytes(b64decode(value) if isinstance(value, str) else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid Ed25519 private key") from exc


def _public(value: Any) -> Ed25519PublicKey:
    if isinstance(value, Ed25519PublicKey):
        return value
    try:
        return Ed25519PublicKey.from_public_bytes(b64decode(value) if isinstance(value, str) else value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid Ed25519 public key") from exc


def _validate_body(body: Any, now: str | datetime | None = None) -> None:
    if not isinstance(body, dict) or set(body) != BODY_KEYS:
        raise ValueError("Invalid signed envelope fields")
    if body["type"] not in MESSAGE_TYPES or type(body["schema_version"]) is not int or body["schema_version"] != 1:
        raise ValueError("Unsupported message type or schema version")
    for field in ("message_id", "issuer", "circle_id", "nonce", "key_id"):
        if not isinstance(body[field], str) or not 1 <= len(body[field]) <= 200:
            raise ValueError(f"Invalid {field}")
    if len(body["nonce"]) < 16:
        raise ValueError("Nonce is too short")
    audiences = body["audience"]
    if not isinstance(audiences, list) or not audiences or any(not isinstance(a, str) or not a for a in audiences) or len(set(audiences)) != len(audiences):
        raise ValueError("Invalid audience")
    if type(body["consent_revision"]) is not int or body["consent_revision"] < 0:
        raise ValueError("Invalid consent revision")
    if not isinstance(body["payload"], dict):
        raise ValueError("Invalid message payload")
    issued, expires = parse_time(body["issued_at"]), parse_time(body["expires_at"])
    if expires <= issued:
        raise ValueError("Expiry must follow issuance")
    if now is not None:
        instant = parse_time(now) if isinstance(now, str) else now
        if instant.tzinfo is None:
            raise ValueError("Verification time must be timezone aware")
        if instant >= expires:
            raise ValueError("Message has expired")
        if issued > instant + timedelta(seconds=30):
            raise ValueError("Message issued in the future")


def sign_message(private_key: Any, body: dict) -> dict:
    _validate_body(body)
    return {"body": body, "signature": b64encode(_private(private_key).sign(canonical(body)))}


def verify_message(message: dict, public_key: Any, audience: str | None = None, message_type: str | None = None, now: str | datetime | None = None) -> dict:
    if not isinstance(message, dict) or set(message) != {"body", "signature"}:
        raise ValueError("Invalid signed message")
    body = message["body"]
    _validate_body(body, now=utc_now() if now is None else now)
    if audience is not None and audience not in body["audience"]:
        raise ValueError("Wrong message audience")
    if message_type is not None and body["type"] != message_type:
        raise ValueError("Wrong message type")
    try:
        _public(public_key).verify(b64decode(message["signature"]), canonical(body))
    except (InvalidSignature, ValueError, TypeError) as exc:
        raise ValueError("Invalid Ed25519 signature") from exc
    return body


def new_identity(path: str | Path, owner_id: str) -> dict:
    path = Path(path)
    if path.exists() and path.is_dir():
        path = path / "identity.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    if not path.exists():
        key = Ed25519PrivateKey.generate()
        raw_private = key.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
        raw_public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        content = {"owner_id": owner_id, "private_key": b64encode(raw_private), "public_key": b64encode(raw_public), "key_id": f"{owner_id}-{hashlib.sha256(raw_public).hexdigest()[:20]}"}
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as handle:
                json.dump(content, handle)
                handle.flush()
                os.fsync(handle.fileno())
    content = json.loads(path.read_text())
    if content.get("owner_id") != owner_id:
        raise ValueError("Identity belongs to another owner")
    private = _private(content["private_key"])
    derived = b64encode(private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    if derived != content.get("public_key"):
        raise ValueError("Identity key mismatch")
    os.chmod(path, 0o600)
    return {"private_key": private, "public_key": derived, "key_id": content["key_id"]}


def envelope(owner_id: str, key_id: str, message_type: str, payload: dict, consent_revision: int, audience: list[str], ttl: int = 3600) -> dict:
    body = {"type": message_type, "schema_version": 1, "message_id": str(uuid.uuid4()), "issuer": owner_id, "audience": audience, "circle_id": "dev-circle", "issued_at": utc_now(), "expires_at": expires_in(ttl), "nonce": secrets.token_urlsafe(24), "key_id": key_id, "consent_revision": consent_revision, "payload": payload}
    _validate_body(body)
    return body
