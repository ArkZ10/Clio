"""Per-stage model routing policy.

Pure lookup: given a pipeline stage name, which registered llm_switch
endpoint should run it? No live calls, no HTTP -- this only decides WHICH
endpoint, never invokes one. Per-stage by design (build-spec.md §4b): no
global toggle, no env-var override -- just this table.
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
    # All five currently route to "deepseek" (direct DeepSeek API,
    # deepseek-v4-flash) -- a user choice. The table is still per-stage: each
    # entry is independent and can be repointed individually; the values just
    # happen to coincide right now. The "nvidia" endpoint stays registered as
    # a fallback.
    Stage.CLUSTER_LABEL.value: "deepseek",
    Stage.RERANK.value: "deepseek",
    Stage.EXTRACT.value: "deepseek",
    Stage.SYNTHESIS.value: "deepseek",
    # Vault chat (V2). Runs BOTH steps of index-first retrieval: page selection
    # and grounded answering.
    Stage.CHAT.value: "deepseek",
}


def route_name(stage: str) -> str:
    """The endpoint NAME a stage routes to, per DEFAULT_ROUTES. No llm_switch
    lookup -- just the table, so this can be asserted without any endpoint
    being registered."""
    if stage not in DEFAULT_ROUTES:
        raise ValueError(
            f"Unknown stage: {stage!r}. Valid stages: {sorted(DEFAULT_ROUTES)}"
        )
    return DEFAULT_ROUTES[stage]


def resolve_stage(stage: str):
    """The actual llm_switch endpoint object a stage routes to. Raises if the
    stage is unknown. get_endpoint() returns None (not an exception) for an
    unregistered endpoint, so that's checked explicitly here and turned into
    the same LLMError shape llm_switch itself uses for "not found" -- never
    silently returned as None, never swallowed."""
    name = route_name(stage)
    endpoint = llm_switch.get_endpoint(name)
    if endpoint is None:
        raise llm_switch.LLMError(
            404, f"Stage '{stage}' routes to endpoint '{name}', which is not registered"
        )
    return endpoint
