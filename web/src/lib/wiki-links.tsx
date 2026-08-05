/**
 * Obsidian-style [[Page]] / [[Page|Alias]] wikilinks, shared between the vault
 * page viewer (routes/vault.tsx) and chat answers (components/clio/chat-
 * surface.tsx) -- the backend's ANSWER_SYSTEM_PROMPT (backend/chat.py) asks
 * the model to cite inline in this same [[Page]] form, so both render sites
 * need the same handling.
 *
 * Split into a parse-time half and a render-time half:
 *   - remarkWikiLinks turns `[[..]]` into a real mdast link node with a
 *     `wiki:<encoded target>` URL. It has no idea which pages actually exist
 *     -- that's not available at parse time -- so it never decides resolved
 *     vs. unresolved.
 *   - makeStemResolver + makeWikiLinkRenderer do that resolution at render
 *     time, against whatever stems the caller actually has loaded. Case-
 *     insensitive fallback mirrors build_graph's lower_to_stem in
 *     backend/vault.py, so a link that resolves on the backend graph resolves
 *     here too.
 *
 * Unresolved links render as plain dim text, never a broken link or a
 * "create page" prompt -- the vault is read-only end to end, there is nothing
 * to create.
 */
import type { ReactNode } from "react";
import type { Root } from "mdast";
import { findAndReplace } from "mdast-util-find-and-replace";
import { defaultUrlTransform } from "react-markdown";

const WIKI_SCHEME = "wiki:";

const WIKILINK_RE = /\[\[([^[\]]+?)\]\]/g;

/** Splits `Target|Alias` on the first (optionally backslash-escaped) pipe.
 *  The escaped form shows up inside GFM table cells -- backend/vault.py's
 *  _ALIAS_SPLIT_RE documents why -- and by the time remark-gfm has parsed the
 *  cell into a text node the backslash may or may not still be there, so both
 *  are matched here. */
function splitAlias(inner: string): [string, string | undefined] {
  const m = inner.match(/\\?\|/);
  if (!m || m.index === undefined) return [inner, undefined];
  return [inner.slice(0, m.index), inner.slice(m.index + m[0].length)];
}

/** Mirrors backend/vault.py's parse_links target normalisation: drop a
 *  #Heading or ^block suffix and a folder/ prefix, so the same source text
 *  resolves to the same stem on both ends. */
function normalizeTarget(raw: string): string {
  return raw.split("#")[0]!.split("^")[0]!.split("/").pop()!.trim();
}

/** Remark plugin: [[Target]] / [[Target|Alias]] -> a link node pointing at
 *  `wiki:<encoded target>`. Runs after remarkGfm in the plugin list so table
 *  cells are already split correctly before this scans their text nodes. */
export function remarkWikiLinks() {
  return (tree: Root) => {
    findAndReplace(tree, [
      [
        WIKILINK_RE,
        (_match: string, inner: string) => {
          const [rawTarget, rawAlias] = splitAlias(inner);
          const target = normalizeTarget(rawTarget);
          if (!target) return false; // malformed -- leave the source text as-is
          const label = (rawAlias ?? rawTarget).trim() || target;
          return {
            type: "link",
            url: `${WIKI_SCHEME}${encodeURIComponent(target)}`,
            children: [{ type: "text", value: label }],
          };
        },
      ],
    ]);
  };
}

/** Decodes a `wiki:<target>` href back to the raw target text, or null if
 *  `href` isn't one of ours (a normal http(s) link). */
function wikiLinkTarget(href: string | undefined): string | null {
  if (!href?.startsWith(WIKI_SCHEME)) return null;
  return decodeURIComponent(href.slice(WIKI_SCHEME.length));
}

/** react-markdown's default `urlTransform` allowlists http(s)/mailto/etc and
 *  blanks any other URL scheme -- including ours -- before a link ever
 *  reaches `components.a`, as an XSS guard against things like `javascript:`
 *  hrefs. That silently turned every wikilink into a `href=""` anchor, which
 *  is why clicking one just reopened the current page in a new tab instead of
 *  reaching makeWikiLinkRenderer at all. Pass this as the `urlTransform` prop
 *  everywhere remarkWikiLinks is used, so `wiki:` URLs pass through untouched
 *  while everything else keeps the default sanitisation. */
export function wikiAwareUrlTransform(value: string): string {
  return value.startsWith(WIKI_SCHEME) ? value : defaultUrlTransform(value);
}

/** Case-insensitive lookup against a known set of vault stems. Exact match
 *  wins; every link in the vault is currently exact-case, so the lowercase
 *  fallback only ever helps -- same tradeoff as backend/vault.py's
 *  lower_to_stem. */
export function makeStemResolver(stems: Iterable<string>) {
  const exact = new Set(stems);
  const lower = new Map<string, string>();
  for (const s of exact) {
    if (!lower.has(s.toLowerCase())) lower.set(s.toLowerCase(), s);
  }
  return (target: string): string | null =>
    exact.has(target) ? target : (lower.get(target.toLowerCase()) ?? null);
}

/** ReactMarkdown `components.a` override for a tree that's been through
 *  remarkWikiLinks: resolved wikilinks become a clickable button (styling
 *  matches a link, not a button, since that's what it reads as), unresolved
 *  ones become plain dim text, and anything that isn't a `wiki:` href passes
 *  through as a normal external link. `resolve`/`onNavigate` are both
 *  optional so callers with no stem list or nowhere to navigate to (chat on
 *  `/` and `/library` has no page viewer) degrade to inert styled text rather
 *  than a link to nowhere. */
export function makeWikiLinkRenderer(
  resolve: ((target: string) => string | null) | undefined,
  onNavigate: ((stem: string) => void) | undefined,
) {
  return function WikiAwareLink({
    href,
    children,
  }: {
    href?: string | undefined;
    children?: ReactNode | undefined;
  }) {
    const target = wikiLinkTarget(href);
    if (target === null) {
      return (
        <a
          href={href}
          target="_blank"
          rel="noreferrer"
          className="underline underline-offset-2"
        >
          {children}
        </a>
      );
    }
    const resolved = resolve?.(target) ?? null;
    if (resolved && onNavigate) {
      return (
        <button
          type="button"
          onClick={() => onNavigate(resolved)}
          className="text-primary underline decoration-primary/40 underline-offset-2 hover:decoration-primary"
        >
          {children}
        </button>
      );
    }
    return (
      <span
        className="text-muted-foreground/70"
        title={resolved ? undefined : "Not in your wiki"}
      >
        {children}
      </span>
    );
  };
}
