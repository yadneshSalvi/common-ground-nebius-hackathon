from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from run import provision
from run_isolated import configs, profile_plan, provider_file


def test_fictional_session_gate_is_opt_in_and_old_store_is_preserved(tmp_path):
    old = tmp_path / "historical"
    config = provision(old)
    before = config.read_bytes()
    assert json.loads(before)["fictional_sample"] is False
    with pytest.raises(ValueError, match="new --runtime"):
        provision(old, fictional_sample=True)
    assert config.read_bytes() == before
    fresh = provision(tmp_path / "fresh", fictional_sample=True)
    assert json.loads(fresh.read_text())["fictional_sample"] is True
    for owner in ("asha", "ravi", "leena"):
        assert json.loads((fresh.parent / "owners" / owner / "config.json").read_text())["fictional_sample"] is True


def test_container_profile_has_disjoint_volumes_no_host_or_socket_mounts():
    plan = profile_plan("cg-test", "pinned-image")
    mounts = []
    for name, service in plan.items():
        args = service["argv"]
        assert "--read-only" in args and "--cap-drop=ALL" in args
        assert "--security-opt=no-new-privileges" in args
        assert "--user=1000:1000" in args
        assert all("type=bind" not in arg and "docker.sock" not in arg for arg in args)
        mounts.extend((service["config_volume"], service["data_volume"]))
        assert service["network"] == ("cg-test-egress" if name == "broker" else f"cg-test-{name}-private")
    assert len(set(mounts)) == 8


def test_owner_configs_never_receive_other_owner_keys_or_provider_file(tmp_path):
    result = configs(tmp_path / "profile", fictional_sample=True)
    for name in ("asha", "ravi", "leena"):
        own = result[name]
        assert own["origin"] == f'http://127.0.0.1:{own["port"]}'
        assert "env_path" not in own and "owners" not in own
        assert "dist_dir" in own and own["data_dir"] == "/data"
        for other in ("asha", "ravi", "leena"):
            if name != other:
                assert result[other]["service_token"] not in json.dumps(own)
                assert result[other]["pair_code"] not in json.dumps(own)
    for peer in result["broker"]["owners"]:
        assert peer["url"] == f'http://{peer["id"]}:{result[peer["id"]]["port"]}'
        assert peer["browser_url"] == result[peer["id"]]["origin"]
    broker_text = json.dumps(result["broker"])
    for name in ("asha", "ravi", "leena"):
        assert result[name]["pair_code"] not in broker_text
    assert result["broker"]["env_path"] == "/config/provider.env"


def test_broker_provider_file_is_an_allowlist_not_parent_env_copy(tmp_path, monkeypatch):
    for name in ("FIREWORKS_AI_API_KEY", "FIREWORKS_API_KEY", "NEBIUS_API_KEY", "TOGETHER_API_KEY", "TOGETHER_AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    source = tmp_path / ".env"
    source.write_text('FIREWORKS_AI_API_KEY="synthetic-development-key"\nNEBIUS_API_KEY="synthetic-final-key"\nGMAIL_TOKEN="must-not-enter-broker"\nTAVILY_API_KEY="also-not-needed"\n')
    filtered = provider_file(source)
    assert "synthetic-development-key" in filtered and "synthetic-final-key" in filtered
    assert "must-not-enter-broker" not in filtered and "also-not-needed" not in filtered
