import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { AlertTriangle, FileText, MessageSquare, X } from "lucide-react";
import { GraphView, type GraphViewNode } from "@/components/clio/graph-view";
import { ChatSurface } from "@/components/clio/chat-surface";
import { PageMeta } from "@/components/clio/page-meta";
import {
  CATEGORY_LABEL,
  VAULT_CATEGORIES,
  colorForCategory,
  fetchVaultGraph,
  fetchVaultPage,
  type VaultCategory,
} from "@/lib/vault";
import {
  makeStemResolver,
  makeWikiLinkRenderer,
  remarkWikiLinks,
  wikiAwareUrlTransform,
} from "@/lib/wiki-links";

/** ?page=<stem> -- lets Library's "Read note" link straight into a page.
 *  Anything malformed just drops to the normal empty state. */
function validateSearch(search: Record<string, unknown>): { page?: string } {
  const page = search["page"];
  return typeof page === "string" && page ? { page } : {};
}

export const Route = createFileRoute("/vault")({
  validateSearch,
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
  // Seeds the initially-open page from ?page=<stem>, read once on mount.
  const { page: initialPage } = Route.useSearch();
  const [selectedStem, setSelectedStem] = useState<string | null>(initialPage ?? null);
  const [chatOpen, setChatOpen] = useState(false);
  // Captured when chat opens, held apart from selectedStem so browsing to
  // another page mid-conversation doesn't change what it's anchored to.
  const [chatContext, setChatContext] = useState<string | null>(null);
  const detailScrollRef = useRef<HTMLDivElement>(null);

  // The scroll container doesn't remount on a page swap, so its old scroll
  // offset would otherwise carry over and land you mid-scroll on blank space.
  useEffect(() => {
    detailScrollRef.current?.scrollTo({ top: 0 });
  }, [selectedStem]);

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

  // Resolves a cited stem to title + category for the chat chips.
  const nodeByStem = useMemo(() => {
    const map = new Map<string, { title: string; category: string }>();
    for (const n of graph?.nodes ?? []) {
      map.set(n.id, { title: n.title, category: n.category });
    }
    return map;
  }, [graph]);

  const resolveStem = useMemo(() => makeStemResolver(nodeByStem.keys()), [nodeByStem]);

  // Clicking a resolved wikilink navigates within this page, same as a node.
  const wikiLinkComponent = useMemo(
    () => makeWikiLinkRenderer(resolveStem, setSelectedStem),
    [resolveStem],
  );

  const openChat = (context: string | null) => {
    setChatContext(context);
    setChatOpen(true);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">
          Vault · wikilink graph
        </h1>
        {/* Stats line doubles as a sanity check for data bugs. */}
        <div className="flex items-center gap-3">
          {stats && (
            <p className="font-mono text-xs text-muted-foreground">
              {stats.n_nodes} nodes · {stats.n_links} links ·{" "}
              <span className={stats.n_unresolved > 0 ? "text-destructive" : undefined}>
                {stats.n_unresolved} unresolved
              </span>{" "}
              · {stats.n_orphans} orphans
            </p>
          )}
          <button
            onClick={() => openChat(null)}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Ask your wiki
          </button>
        </div>
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
            <div
              ref={detailScrollRef}
              className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-border bg-surface p-5 lg:w-2/5"
            >
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
                  <div className="flex flex-wrap items-center justify-between gap-2">
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
                    <div className="flex shrink-0 items-center gap-2">
                      {/* Lives here, not in GraphView -- onSelect only yields a stem. */}
                      <button
                        onClick={() => openChat(selectedStem)}
                        className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-2.5 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                      >
                        <MessageSquare className="h-3.5 w-3.5" />
                        Ask about this page
                      </button>
                      <button
                        onClick={() => setSelectedStem(null)}
                        className="rounded-lg p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                        aria-label="Close page"
                      >
                        <X className="h-4 w-4" />
                      </button>
                    </div>
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
                      remarkPlugins={[remarkGfm, remarkWikiLinks]}
                      urlTransform={wikiAwareUrlTransform}
                      components={{
                        // Wide evidence tables scroll inside the panel instead
                        // of stretching the layout.
                        table: ({ children, ...props }) => (
                          <div className="table-scroll">
                            <table {...props}>{children}</table>
                          </div>
                        ),
                        a: wikiLinkComponent,
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

      {/* Slide-over vault chat -- same pattern as library.tsx's panel. */}
      {chatOpen && (
        <div className="fixed inset-0 z-50 flex">
          <div
            className="flex-1 bg-black/60 backdrop-blur-[2px]"
            onClick={() => setChatOpen(false)}
          />
          <div className="flex h-full w-full max-w-[480px] flex-col border-l border-border bg-background shadow-panel">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <h2 className="truncate text-sm font-medium">
                  {chatContext ? `Ask about ${chatContext}` : "Ask your wiki"}
                </h2>
                <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground">
                  Grounded
                </span>
              </div>
              <button
                onClick={() => setChatOpen(false)}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                aria-label="Close vault chat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <ChatSurface
                surface="vault"
                compact
                pageContext={chatContext}
                emptyTitle={chatContext ? "Ask about this page" : "Ask your wiki"}
                emptySubtitle={
                  chatContext
                    ? `Answers always include “${chatContext}”, plus anything else the index points to.`
                    : "Answers come only from your wiki pages. If it isn't in there, Clio says so."
                }
                suggestions={
                  chatContext
                    ? ["Summarise this page", "What does this rest on?", "What's unresolved here?"]
                    : [
                        "What decides output safety?",
                        "Which claims are contested?",
                        "What open questions am I tracking?",
                      ]
                }
                resolvePage={(stem) => nodeByStem.get(stem)}
                resolveStem={resolveStem}
                onCitationClick={(stem) => {
                  setSelectedStem(stem);
                  setChatOpen(false);
                }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
