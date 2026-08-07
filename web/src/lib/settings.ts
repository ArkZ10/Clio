/** Client for the Settings page: llm_switch's endpoint registry and
 *  per-stage routing. Key values never come back from the backend -- see
 *  backend/llm_settings.py -- only whether one's set and how. */
import { deleteJson, getJson, postJson, putJson } from "@/lib/api";

export type EndpointKind = "auto" | "local" | "api";

export type LlmEndpoint = {
  name: string;
  base_url: string;
  kind: EndpointKind;
  default_model: string | null;
  is_local: boolean;
  provider: string;
  has_key: boolean;
  key_source: "env" | "stored" | null;
  key_env_var: string | null;
};

export const fetchEndpoints = () => getJson<{ endpoints: LlmEndpoint[] }>("/settings/endpoints");

/** Creates a new endpoint, or edits an existing one if `name` matches --
 *  llm_switch keys the registry on name. Leave `api_key` unset on an edit to
 *  keep the existing key; the backend never wipes it just because a field
 *  was omitted. */
export const saveEndpoint = (body: {
  name: string;
  base_url: string;
  api_key?: string | null | undefined;
  kind: EndpointKind;
  default_model?: string | null | undefined;
}) => postJson<{ ok: boolean }>("/settings/endpoints", body);

export const deleteEndpoint = (name: string) =>
  deleteJson<{ ok: boolean }>(`/settings/endpoints/${encodeURIComponent(name)}`);

/** The five pipeline stages, in the order the Settings page shows them --
 *  chat first since it's the only one live in the web app. */
export const STAGES = ["chat", "cluster_label", "rerank", "extract", "synthesis"] as const;
export type Stage = (typeof STAGES)[number];

export const STAGE_LABELS: Record<Stage, string> = {
  chat: "Chat",
  cluster_label: "Cluster labeling",
  rerank: "Rerank",
  extract: "Extraction",
  synthesis: "Synthesis",
};

export type StageRoute = {
  stage: Stage;
  endpoint_name: string;
  default_endpoint_name: string;
  is_override: boolean;
};

export const fetchRouting = () => getJson<{ routing: StageRoute[] }>("/settings/routing");

export const setStageRoute = (stage: Stage, endpointName: string) =>
  putJson<{ ok: boolean }>(`/settings/routing/${stage}`, { endpoint_name: endpointName });

export const resetStageRoute = (stage: Stage) =>
  deleteJson<{ ok: boolean }>(`/settings/routing/${stage}`);
