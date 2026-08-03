import pytest

import llm_switch
from llm_switch import store
from backend import routing
from backend.routing import resolve_stage, route_name


def test_route_name_table_is_correct():
    # All four currently route to "deepseek" (direct DeepSeek API,
    # deepseek-v4-flash), a user choice. The "nvidia" endpoint remains
    # registered as a fallback.
    assert route_name("cluster_label") == "deepseek"
    assert route_name("rerank") == "deepseek"
    assert route_name("extract") == "deepseek"
    assert route_name("synthesis") == "deepseek"


def test_routing_is_per_stage_not_a_global_constant(monkeypatch):
    """The values currently all coincide on 'nvidia', so we can no longer
    prove per-stage routing by asserting two stages differ. Instead prove the
    MECHANISM: each stage has its own independent DEFAULT_ROUTES entry, and
    repointing ONE stage changes only that stage -- i.e. it's a table lookup,
    not a single hardcoded global."""
    # Each stage is an independent key.
    assert set(routing.DEFAULT_ROUTES) == {
        "cluster_label", "rerank", "extract", "synthesis"
    }
    # Repoint exactly one entry; only that stage must change.
    monkeypatch.setitem(routing.DEFAULT_ROUTES, "extract", "local-ollama")
    assert route_name("extract") == "local-ollama"
    assert route_name("synthesis") == "deepseek"  # untouched
    assert route_name("extract") != route_name("synthesis")


def test_unknown_stage_raises_value_error():
    with pytest.raises(ValueError):
        route_name("does_not_exist")


@pytest.fixture
def registered_endpoints(tmp_path, monkeypatch):
    """Register the two real endpoint URLs into an ISOLATED registry (not
    ~/.llm_switch/endpoints.json) so resolve_stage's llm_switch lookup has
    something to find without mutating the real registry on every test run.
    No network involved -- get_endpoint is a local registry read."""
    monkeypatch.setattr(store, "_STORE_PATH", tmp_path / "endpoints.json")
    llm_switch.register_endpoint("local-ollama", "http://localhost:11434", kind="auto")
    llm_switch.register_endpoint("deepseek", "https://api.deepseek.com", kind="auto")
    llm_switch.register_endpoint(
        "nvidia", "https://integrate.api.nvidia.com/v1", kind="auto"
    )


def test_resolve_stage_returns_correct_endpoint_object(registered_endpoints):
    synthesis_endpoint = resolve_stage("synthesis")
    assert synthesis_endpoint.name == "deepseek"

    extract_endpoint = resolve_stage("extract")
    assert extract_endpoint.name == "deepseek"

    cluster_label_endpoint = resolve_stage("cluster_label")
    assert cluster_label_endpoint.name == "deepseek"
