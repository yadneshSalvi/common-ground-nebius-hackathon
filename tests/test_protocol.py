from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from shared.protocol import canonical, digest, envelope, expires_in, new_identity, sign_message, utc_now, verify_message


def test_canonical_rfc8785_and_identity_persistence(tmp_path):
    assert canonical({"z": 1.0, "a": [True, "é"]}) == '{"a":[true,"é"],"z":1}'.encode()
    identity = new_identity(tmp_path / "identity.json", "asha")
    again = new_identity(tmp_path / "identity.json", "asha")
    assert identity["public_key"] == again["public_key"]
    assert (tmp_path / "identity.json").stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError):
        new_identity(tmp_path / "identity.json", "ravi")
    with pytest.raises(ValueError):
        canonical({"number": float("nan")})


def test_signature_binds_entire_envelope_and_audience(tmp_path):
    identity = new_identity(tmp_path / "identity.json", "asha")
    body = envelope("asha", identity["key_id"], "Approval", {"purpose": "test"}, 2, ["common-ground-broker"])
    message = sign_message(identity["private_key"], body)
    assert verify_message(message, identity["public_key"], "common-ground-broker", "Approval") == body
    for field, value in (("issuer", "ravi"), ("consent_revision", 3), ("payload", {"purpose": "changed"}), ("audience", ["other"])):
        changed = deepcopy(message)
        changed["body"][field] = value
        with pytest.raises(ValueError):
            verify_message(changed, identity["public_key"])
    with pytest.raises(ValueError, match="audience"):
        verify_message(message, identity["public_key"], "ravi")
    with pytest.raises(ValueError, match="type"):
        verify_message(message, identity["public_key"], message_type="Withdrawal")
    other = new_identity(tmp_path / "other.json", "ravi")
    with pytest.raises(ValueError):
        verify_message(message, other["public_key"])


def test_expiry_future_unknown_fields_and_invalid_signatures(tmp_path):
    identity = new_identity(tmp_path / "identity.json", "asha")
    body = envelope("asha", identity["key_id"], "Withdrawal", {}, 1, ["common-ground-broker"])
    message = sign_message(identity["private_key"], body)
    with pytest.raises(ValueError, match="expired"):
        verify_message(message, identity["public_key"], now=expires_in(7200))
    with pytest.raises(ValueError, match="future"):
        verify_message(message, identity["public_key"], now=(datetime.now(timezone.utc) - timedelta(hours=1)))
    bad = deepcopy(body)
    bad["private_reason"] = "no"
    with pytest.raises(ValueError):
        sign_message(identity["private_key"], bad)
    bad_message = deepcopy(message)
    bad_message["signature"] = "!"
    with pytest.raises(ValueError):
        verify_message(bad_message, identity["public_key"])
    bad_message["signature"] = "AA"
    with pytest.raises(ValueError):
        verify_message(bad_message, identity["public_key"])
    assert digest(body) == digest(json.loads(json.dumps(body, sort_keys=True)))
