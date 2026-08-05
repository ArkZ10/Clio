/**
 * Obsidian-style [[Page]] / [[Page|Alias]] wikilinks, shared by the vault page
 * viewer and chat answers (the model cites inline in this same form).
 *
 * Two halves: remarkWikiLinks turns `[[..]]` into a link node with a
 * `wiki:<target>` URL at parse time, before it's known which pages exist.
 * makeStemResolver + makeWikiLinkRenderer resolve that at render time against
 * whatever stems the caller has loaded (case-insensitive, mirrors
 * backend/vault.py's lower_to_stem).
 *
 * Unresolved links render as plain dim text -- never a broken link or a
 * "create page" prompt, the vault is read-only.
 */
import type { ReactNode } from "react";
import type { Root } from "mdast";
import { findAndReplace } from "mdast-util-find-and-replace";
import { defaultUrlTransform } from "react-markdown";

const WIKI_SCHEME = "wiki:";

const WIKILINK_RE = /\[\[([^[\]]+?)\]\]/g;

/** Splits `Target|Alias` on the first (optionally backslash-escaped) pipe --
 *  the escaped form shows up in GFM table cells, see backend/vault.py's
 *  _ALIAS_SPLIT_RE. */
function splitAlias(inner: string): [string, string | undefined] {
  const m = inner.match(/\\?\|/);
  if (!m || m.index === undefined) return [inner, undefined];
  return [inner.slice(0, m.index), inner.slice(m.index + m[0].length)];
}

/** Mirrors backend/vault.py's parse_links: drop a #Heading/^block suffix and
 *  a folder/ prefix. */
function normalizeTarget(raw: string): string {
  return raw.split("#")[0]!.split("^")[0]!.split("/").pop()!.trim();
}

/** [[Target]] / [[Target|Alias]] -> a link node pointing at
 *  `wiki:<encoded target>`. Run after remarkGfm so table cells are already
 *  split. */
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

/** Decodes a `wiki:<target>` href, or null for a normal http(s) link. */
function wikiLinkTarget(href: string | undefined): string | null {
  if (!href?.startsWith(WIKI_SCHEME)) return null;
  return decodeURIComponent(href.slice(WIKI_SCHEME.length));
}

/** react-markdown's default urlTransform blanks any URL scheme it doesn't
 *  allowlist (an XSS guard), which silently killed every wikilink href before
 *  it reached makeWikiLinkRenderer. Pass this as `urlTransform` wherever
 *  remarkWikiLinks is used -- `wiki:` passes through, everything else keeps
 *  the default sanitisation. */
export function wikiAwareUrlTransform(value: string): string {
  return value.startsWith(WIKI_SCHEME) ? value : defaultUrlTransform(value);
}

/** Case-insensitive lookup against a known set of vault stems. Exact match
 *  wins, same as backend/vault.py's lower_to_stem. */
export function makeStemResolver(stems: Iterable<string>) {
  const exact = new Set(stems);
  const lower = new Map<string, string>();
  for (const s of exact) {
    if (!lower.has(s.toLowerCase())) lower.set(s.toLowerCase(), s);
  }
  return (target: string): string | null =>
    exact.has(target) ? target : (lower.get(target.toLowerCase()) ?? null);
}

/** `components.a` override for a tree that's been through remarkWikiLinks:
 *  resolved wikilinks become a clickable button styled as a link, unresolved
 *  ones become plain dim text, everything else passes through as a normal
 *  external link. `resolve`/`onNavigate` are optional so a caller with
 *  nowhere to navigate to just gets inert styled text. */
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
