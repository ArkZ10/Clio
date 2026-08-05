/** Frontmatter as compact chips + tags, shared by every place a vault page
 *  gets rendered (routes/vault.tsx's detail pane, routes/library.tsx's note
 *  panel). Replaces dumping the raw YAML into the markdown renderer, which
 *  produced a wall of bold `key: value` text. */

/** Frontmatter fields worth surfacing, in display order. The rest (title,
 *  created, sources, ...) are either shown elsewhere or too noisy for a header. */
const META_FIELDS = [
  "type",
  "status",
  "verdict",
  "confidence",
  "evidence",
  "year",
  "venue",
  "design",
  "n",
  "replication",
  "updated",
] as const;

function metaText(value: unknown): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (Array.isArray(value)) {
    const joined = value.filter(Boolean).join(", ");
    return joined || null;
  }
  if (typeof value === "object") return null;
  return String(value);
}

export function PageMeta({ meta }: { meta: Record<string, unknown> }) {
  const fields: Array<[string, string]> = [];
  for (const key of META_FIELDS) {
    const value = metaText(meta[key]);
    if (value !== null) fields.push([key, value]);
  }
  const tags = Array.isArray(meta["tags"]) ? (meta["tags"] as unknown[]).map(String) : [];

  if (fields.length === 0 && tags.length === 0) return null;

  return (
    <div className="mt-4 space-y-2 rounded-lg border border-border bg-elevated/40 px-3 py-2.5">
      {fields.length > 0 && (
        <dl className="flex flex-wrap gap-x-4 gap-y-1.5 text-xs">
          {fields.map(([key, value]) => (
            <div key={key} className="flex items-baseline gap-1.5">
              <dt className="text-muted-foreground capitalize">{key}</dt>
              <dd className="text-foreground">{value}</dd>
            </div>
          ))}
        </dl>
      )}
      {tags.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {tags.map((tag) => (
            <span
              key={tag}
              className="rounded-full bg-secondary/50 px-2 py-0.5 text-[11px] text-muted-foreground"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
