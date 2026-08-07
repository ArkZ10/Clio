/** Shared HTTP client primitives for talking to the FastAPI backend --
 *  everything under lib/*.ts (vault.ts, settings.ts) builds on these instead
 *  of each rolling its own fetch wrapper. */

/** Base URL of the FastAPI backend -- set VITE_API_URL in web/.env. Missing
 *  config fails loudly below rather than fetching "undefined/vault/graph". */
const API_URL = import.meta.env.VITE_API_URL;

export function apiBase(): string {
  if (!API_URL) {
    throw new Error(
      "VITE_API_URL is not set. Copy web/.env.example to web/.env and set it to the backend URL (e.g. http://localhost:8000), then restart the dev server.",
    );
  }
  return API_URL.replace(/\/$/, "");
}

/** Surfaces the backend's `detail` message instead of a bare status code. */
export async function toError(res: Response, path: string): Promise<Error> {
  let detail = "";
  try {
    detail = ((await res.json()) as { detail?: string }).detail ?? "";
  } catch {
    /* non-JSON body: fall through to the status-only message */
  }
  return new Error(detail || `Request to ${path} failed (HTTP ${res.status})`);
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

export async function putJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

export async function deleteJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, { method: "DELETE" });
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}
