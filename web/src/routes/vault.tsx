import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, FileText } from "lucide-react";
import { GraphView, type GraphViewNode } from "@/components/clio/graph-view";
import {
  CATEGORY_LABEL,
  VAULT_CATEGORIES,
  colorForCategory,
  fetchVaultGraph,
  fetchVaultPage,
  type VaultCategory,
} from "@/lib/vault";

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

/** Frontmatter as compact chips + tags. Replaces dumping the raw YAML into the
 *  markdown renderer, which produced a wall of bold `key: value` text. */
function PageMeta({ meta }: { meta: Record<string, unknown> }) {
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

export const Route = createFileRoute("/vault")({
  head: () => ({
    meta: [
      { title: "Vault — Clio wikilink graph" },
      {
        name: "description",
        content:
          "Your Obsidian vault as a wikilink graph, coloured by page category, with the source markdown alongside.",
      },
      { property: "og:title", content: "Vault — Clio wikilink graph" },
      {
        property: "og:description",
        content: "The vault's wikilink graph, coloured by page category.",
      },
    ],
  }),
  component: VaultPage,
});

function VaultPage() {
  const [selectedStem, setSelectedStem] = useState<string | null>(null);

  const graphQuery = useQuery({
    queryKey: ["vault", "graph"],
    queryFn: fetchVaultGraph,
  });

  const pageQuery = useQuery({
    queryKey: ["vault", "page", selectedStem],
    queryFn: () => fetchVaultPage(selectedStem!),
    enabled: selectedStem !== null,
  });

  const graph = graphQuery.data;

  const nodes: GraphViewNode[] = useMemo(
    () =>
      (graph?.nodes ?? []).map((n) => ({
        id: n.id,
        title: n.title,
        color: colorForCategory(n.category),
      })),
    [graph],
  );

  // Only categories actually present, so the legend never lists an empty group.
  const presentCategories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const n of graph?.nodes ?? []) {
      counts.set(n.category, (counts.get(n.category) ?? 0) + 1);
    }
    return VAULT_CATEGORIES.filter((c) => counts.has(c)).map((c) => ({
      category: c as VaultCategory,
      count: counts.get(c)!,
    }));
  }, [graph]);

  const stats = graph?.stats;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">
          Vault · wikilink graph
        </h1>
        {/* Stats line: the console-assert equivalent. A data bug (templates
            leaking in, links silently dropped) shows up here even if the
            render looks fine. */}
        {stats && (
          <p className="font-mono text-xs text-muted-foreground">
            {stats.n_nodes} nodes · {stats.n_links} links ·{" "}
            <span className={stats.n_unresolved > 0 ? "text-destructive" : undefined}>
              {stats.n_unresolved} unresolved
            </span>{" "}
            · {stats.n_orphans} orphans
          </p>
        )}
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-4">
        {graphQuery.isPending && (
          <p className="p-4 text-sm text-muted-foreground">Loading vault…</p>
        )}

        {graphQuery.isError && (
          <div className="flex items-start gap-3 rounded-xl border border-border bg-surface p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <div>
              <p className="text-sm font-medium text-foreground">Could not load the vault</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {(graphQuery.error as Error).message}
              </p>
            </div>
          </div>
        )}

        {graph && (
          <div className="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
            {/* Graph pane */}
            <div className="flex min-h-0 flex-col gap-3 lg:w-3/5">
              <div className="min-h-0 flex-1">
                <GraphView
                  nodes={nodes}
                  links={graph.links}
                  selectedId={selectedStem}
                  onSelect={setSelectedStem}
                  footerNote={`${graph.nodes.length} pages · ${graph.links.length} links · hover for the page name, click to read`}
                />
              </div>

              {/* Legend */}
              <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-border bg-surface px-4 py-3">
                {presentCategories.map(({ category, count }) => (
                  <span
                    key={category}
                    className="flex items-center gap-1.5 text-xs text-muted-foreground"
                  >
                    <span
                      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: colorForCategory(category) }}
                    />
                    {CATEGORY_LABEL[category]}
                    <span className="text-muted-foreground/60">{count}</span>
                  </span>
                ))}
              </div>
            </div>

            {/* Detail pane */}
            <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-border bg-surface p-5 lg:w-2/5">
              {!selectedStem && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    Click a node to read the page
                  </p>
                </div>
              )}

              {selectedStem && pageQuery.isPending && (
                <p className="text-sm text-muted-foreground">Loading page…</p>
              )}

              {selectedStem && pageQuery.isError && (
                <p className="text-sm text-destructive">
                  {(pageQuery.error as Error).message}
                </p>
              )}

              {pageQuery.data && (
                <article>
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className="inline-block h-2.5 w-2.5 shrink-0 rounded-full"
                      style={{ backgroundColor: colorForCategory(pageQuery.data.category) }}
                    />
                    <span className="text-xs text-muted-foreground">
                      {CATEGORY_LABEL[pageQuery.data.category as VaultCategory] ??
                        pageQuery.data.category}
                    </span>
                  </div>
                  <h2 className="mt-2 text-lg font-medium text-foreground">
                    {pageQuery.data.title}
                  </h2>
                  <p className="mt-1 font-mono text-xs text-muted-foreground">
                    {pageQuery.data.path}
                  </p>

                  <PageMeta meta={pageQuery.data.meta} />

                  <div className="prose-clio mt-5 text-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        // Wrap tables so a wide evidence table scrolls inside
                        // the panel instead of stretching the whole layout.
                        table: ({ children, ...props }) => (
                          <div className="table-scroll">
                            <table {...props}>{children}</table>
                          </div>
                        ),
                      }}
                    >
                      {pageQuery.data.content}
                    </ReactMarkdown>
                  </div>
                </article>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
