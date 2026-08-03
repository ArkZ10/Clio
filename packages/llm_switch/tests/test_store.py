import json

import pytest

from llm_switch import crypto, store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Redirect the registry file and crypto key into a tmp dir, and reset
    crypto's cached Fernet instance, so tests never touch ~/.llm_switch/."""
    monkeypatch.setattr(store, "_STORE_PATH", tmp_path / "endpoints.json")
    monkeypatch.setattr(crypto, "_KEY_PATH", tmp_path / ".key")
    monkeypatch.setattr(crypto, "_fernet", None)
    yield


def test_env_key_stored_verbatim_no_secret_on_disk(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "sk-super-secret-value")
    store.add_endpoint("ep1", "https://api.example.com", api_key="env:MY_TEST_KEY")

    raw = store._STORE_PATH.read_text()
    assert "env:MY_TEST_KEY" in raw
    assert "sk-super-secret-value" not in raw


def test_env_key_resolves_from_environment(monkeypatch):
    monkeypatch.setenv("MY_TEST_KEY", "sk-super-secret-value")
    store.add_endpoint("ep1", "https://api.example.com", api_key="env:MY_TEST_KEY")

    record = store.get_endpoint("ep1")
    assert store.resolve_api_key(record) == "sk-super-secret-value"


def test_env_key_missing_raises():
    store.add_endpoint("ep1", "https://api.example.com", api_key="env:DOES_NOT_EXIST_XYZ")
    record = store.get_endpoint("ep1")
    with pytest.raises(Exception):
        store.resolve_api_key(record)


def test_literal_secret_is_encrypted_on_disk_and_round_trips():
    store.add_endpoint("ep2", "https://api.example.com", api_key="plain-literal-secret")

    raw = store._STORE_PATH.read_text()
    data = json.loads(raw)
    on_disk_value = data["endpoints"]["ep2"]["api_key"]

    assert on_disk_value.startswith("enc:")
    assert "plain-literal-secret" not in raw

    record = store.get_endpoint("ep2")
    assert store.resolve_api_key(record) == "plain-literal-secret"


def test_no_key_endpoint_resolves_none():
    store.add_endpoint("ep3", "http://localhost:11434", api_key=None)
    record = store.get_endpoint("ep3")
    assert store.resolve_api_key(record) is None


def test_remove_endpoint():
    store.add_endpoint("ep4", "http://localhost:11434")
    assert store.get_endpoint("ep4") is not None

    assert store.remove_endpoint("ep4") is True
    assert store.get_endpoint("ep4") is None
    assert store.remove_endpoint("ep4") is False


def test_list_endpoints_returns_all():
    store.add_endpoint("a", "http://localhost:11434")
    store.add_endpoint("b", "https://api.example.com")
    names = set(store.list_endpoints().keys())
    assert names == {"a", "b"}
