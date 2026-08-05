/**
 * Client for the read-only vault endpoints, plus the category colour scale.
 * Hues are held at similar lightness/saturation to stay on-theme rather than
 * a rainbow, while still being distinguishable at small node sizes.
 */

export const VAULT_CATEGORIES = [
  "sources",
  "claims",
  "concepts",
  "entities",
  "questions",
  "syntheses",
  "root",
] as const;

export type VaultCategory = (typeof VAULT_CATEGORIES)[number];

export const CATEGORY_COLOR: Record<VaultCategory, string> = {
  concepts: "#A855C7", // the Clio primary purple -- the vault's biggest group
  sources: "#D9A441", // amber: the evidence record
  claims: "#E0607E", // rose: contested findings
  entities: "#3FB8A6", // teal: people, labs, models, datasets
  questions: "#4C8DD9", // blue: open questions
  syntheses: "#5FC97A", // green: conclusions drawn across sources
  root: "#8C93A8", // grey: index, log, overview -- structural, not content
};

export const CATEGORY_LABEL: Record<VaultCategory, string> = {
  concepts: "Concepts",
  sources: "Sources",
  claims: "Claims",
  entities: "Entities",
  questions: "Questions",
  syntheses: "Syntheses",
  root: "Index / log",
};

export function colorForCategory(category: string): string {
  return CATEGORY_COLOR[category as VaultCategory] ?? CATEGORY_COLOR.root;
}

export type VaultNode = { id: string; title: string; category: string };
export type VaultLink = { source: string; target: string };
export type VaultStats = {
  n_nodes: number;
  n_links: number;
  n_unresolved: number;
  n_orphans: number;
};
export type VaultGraph = {
  nodes: VaultNode[];
  links: VaultLink[];
  categories: string[];
  stats: VaultStats;
};
export type VaultPage = {
  stem: string;
  /** Human title from frontmatter, falling back to the filename stem. */
  title: string;
  category: string;
  path: string;
  /** Body markdown only -- the YAML frontmatter is parsed out into `meta`. */
  content: string;
  meta: Record<string, unknown>;
};

/** Base URL of the FastAPI backend -- set VITE_API_URL in web/.env. Missing
 *  config fails loudly below rather than fetching "undefined/vault/graph". */
const API_URL = import.meta.env.VITE_API_URL;

function apiBase(): string {
  if (!API_URL) {
    throw new Error(
      "VITE_API_URL is not set. Copy web/.env.example to web/.env and set it to the backend URL (e.g. http://localhost:8000), then restart the dev server.",
    );
  }
  return API_URL.replace(/\/$/, "");
}

/** Surfaces the backend's `detail` message instead of a bare status code. */
async function toError(res: Response, path: string): Promise<Error> {
  let detail = "";
  try {
    detail = ((await res.json()) as { detail?: string }).detail ?? "";
  } catch {
    /* non-JSON body: fall through to the status-only message */
  }
  return new Error(detail || `Request to ${path} failed (HTTP ${res.status})`);
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`);
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

async function deleteJson<T>(path: string): Promise<T> {
  const res = await fetch(`${apiBase()}${path}`, { method: "DELETE" });
  if (!res.ok) throw await toError(res, path);
  return (await res.json()) as T;
}

export const fetchVaultGraph = () => getJson<VaultGraph>("/vault/graph");

export const fetchVaultPage = (stem: string) =>
  getJson<VaultPage>(`/vault/page/${encodeURIComponent(stem)}`);

/** A Library entry -- see backend/vault.py's list_sources. */
export type LibraryPaper = {
  stem: string;
  title: string;
  authors: string[];
  year: number | null;
  venue: string | null;
  evidence: string | null;
  status: string | null;
};

export const fetchLibrary = () => getJson<{ papers: LibraryPaper[] }>("/vault/library");

/** Direct link to a source's PDF -- for a plain `<a href>`, not fetch(). */
export const rawPdfUrl = (stem: string) => `${apiBase()}/vault/raw/${encodeURIComponent(stem)}`;

export type ChatTurn = { role: "user" | "assistant"; content: string };

export type VaultChatResponse = {
  answer: string;
  /** Page stems the answer was grounded in -- structured, not scraped. */
  cited_pages: string[];
  selected_pages: string[];
  /** Page names the model invented that don't resolve to a real page. */
  dropped_count: number;
  /** True when the wiki doesn't cover the question. See backend/chat.py's
   *  answer(). */
  no_coverage: boolean;
};

export const postVaultChat = (body: {
  question: string;
  page_context?: string | null;
  history?: ChatTurn[];
  session_id?: number | null;
}) => postJson<VaultChatResponse>("/vault/chat", body);

/** Which page's chat this is -- each surface keeps its own thread. */
export type ChatSurfaceName = "home" | "library" | "vault";

export type ChatSessionSummary = {
  id: number;
  page_context: string | null;
  title: string;
  created_at: string;
  updated_at: string;
};

export type ChatSessionMessage = {
  role: "user" | "assistant";
  content: string;
  cited_pages: string[];
  selected_pages: string[];
  dropped_count: number | null;
  no_coverage: boolean | null;
  created_at: string;
};

export type ChatSessionDetail = ChatSessionSummary & {
  surface: ChatSurfaceName;
  messages: ChatSessionMessage[];
};

export const fetchChatSessions = (surface: ChatSurfaceName) =>
  getJson<{ sessions: ChatSessionSummary[] }>(
    `/vault/chat/sessions?surface=${encodeURIComponent(surface)}`,
  );

export const fetchChatSession = (id: number) =>
  getJson<ChatSessionDetail>(`/vault/chat/sessions/${id}`);

export const createChatSession = (surface: ChatSurfaceName, pageContext: string | null) =>
  postJson<{ id: number }>("/vault/chat/sessions", {
    surface,
    page_context: pageContext,
  });

export const deleteChatSession = (id: number) =>
  deleteJson<{ ok: boolean }>(`/vault/chat/sessions/${id}`);
