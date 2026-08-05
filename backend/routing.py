"""Per-stage model routing: which llm_switch endpoint runs which pipeline
stage. Pure lookup, no live calls. Per-stage by design -- no global toggle,
no env-var override, just this table.
"""
from enum import Enum

import llm_switch


class Stage(str, Enum):
    CLUSTER_LABEL = "cluster_label"
    RERANK = "rerank"
    EXTRACT = "extract"
    SYNTHESIS = "synthesis"
    CHAT = "chat"


DEFAULT_ROUTES: dict[str, str] = {
    # All five route to deepseek for now; each entry is independent and can
    # be repointed on its own. "nvidia" stays registered as a fallback.
    Stage.CLUSTER_LABEL.value: "deepseek",
    Stage.RERANK.value: "deepseek",
    Stage.EXTRACT.value: "deepseek",
    Stage.SYNTHESIS.value: "deepseek",
    Stage.CHAT.value: "deepseek",
}


def route_name(stage: str) -> str:
    """The endpoint name a stage routes to. No llm_switch lookup -- just the
    table, so this works without any endpoint registered."""
    if stage not in DEFAULT_ROUTES:
        raise ValueError(
            f"Unknown stage: {stage!r}. Valid stages: {sorted(DEFAULT_ROUTES)}"
        )
    return DEFAULT_ROUTES[stage]


def resolve_stage(stage: str):
    """The llm_switch endpoint object a stage routes to. get_endpoint()
    returns None (not an exception) for an unregistered endpoint, so that's
    turned into the same LLMError shape llm_switch itself uses."""
    name = route_name(stage)
    endpoint = llm_switch.get_endpoint(name)
    if endpoint is None:
        raise llm_switch.LLMError(
            404, f"Stage '{stage}' routes to endpoint '{name}', which is not registered"
        )
    return endpoint
