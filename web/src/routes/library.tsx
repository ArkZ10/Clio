import { createFileRoute } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  AlertTriangle,
  ExternalLink,
  FileText,
  Library as LibraryIcon,
  MessageSquare,
  X,
} from "lucide-react";
import { ChatSurface } from "@/components/clio/chat-surface";
import { PageMeta } from "@/components/clio/page-meta";
import {
  fetchLibrary,
  fetchVaultGraph,
  fetchVaultPage,
  rawPdfUrl,
  type LibraryPaper,
} from "@/lib/vault";
import {
  makeStemResolver,
  makeWikiLinkRenderer,
  remarkWikiLinks,
  wikiAwareUrlTransform,
} from "@/lib/wiki-links";

export const Route = createFileRoute("/library")({
  head: () => ({
    meta: [
      { title: "Library — Clio papers" },
      {
        name: "description",
        content: "The papers behind your wiki: read the PDF or the note built from it, side by side.",
      },
      { property: "og:title", content: "Library — Clio papers" },
      {
        property: "og:description",
        content: "The papers behind your wiki, with their PDFs and notes.",
      },
    ],
  }),
  component: LibraryPage,
});

type ViewMode = "pdf" | "note";

function statusColor(status: string | null): string {
  return status === "active" ? "bg-primary" : "bg-muted-foreground/50";
}

function PaperListItem({
  paper,
  active,
  onOpen,
}: {
  paper: LibraryPaper;
  active: boolean;
  onOpen: (mode: ViewMode) => void;
}) {
  return (
    <div
      className={`rounded-lg border p-3 transition-colors ${
        active ? "border-primary/70 bg-elevated" : "border-transparent hover:bg-elevated/60"
      }`}
    >
      <h2 className="text-sm font-medium text-foreground">{paper.title}</h2>
      <p className="mt-1 truncate text-xs text-muted-foreground">
        {paper.authors.length > 0 ? paper.authors.join(", ") : "Authors unknown"}
        {paper.year ? ` · ${paper.year}` : ""}
      </p>
      {(paper.evidence || paper.status) && (
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {paper.status && (
            <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
              <span className={`inline-block h-1.5 w-1.5 rounded-full ${statusColor(paper.status)}`} />
              {paper.status}
            </span>
          )}
          {paper.evidence && (
            <span className="rounded-full bg-secondary/50 px-2 py-0.5 text-[11px] text-muted-foreground">
              Evidence {paper.evidence}
            </span>
          )}
        </div>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button
          onClick={() => onOpen("pdf")}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
            active ? "border-border bg-background text-foreground" : "border-border bg-elevated text-muted-foreground hover:text-foreground"
          }`}
        >
          <ExternalLink className="h-3.5 w-3.5" />
          PDF
        </button>
        <button
          onClick={() => onOpen("note")}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors ${
            active ? "border-border bg-background text-foreground" : "border-border bg-elevated text-muted-foreground hover:text-foreground"
          }`}
        >
          <FileText className="h-3.5 w-3.5" />
          Note
        </button>
      </div>
    </div>
  );
}

function LibraryPage() {
  const [selectedStem, setSelectedStem] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode | null>(null);
  const [chatOpen, setChatOpen] = useState(false);
  const viewerScrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    viewerScrollRef.current?.scrollTo({ top: 0 });
  }, [selectedStem, viewMode]);

  const libraryQuery = useQuery({
    queryKey: ["vault", "library"],
    queryFn: fetchLibrary,
  });

  // Needed only to resolve [[wikilinks]] inside a note to real stems, so a
  // link out of a paper's note (into a claim, say) can still be followed
  // in place rather than reading as dead text.
  const graphQuery = useQuery({
    queryKey: ["vault", "graph"],
    queryFn: fetchVaultGraph,
  });

  const pageQuery = useQuery({
    queryKey: ["vault", "page", selectedStem],
    queryFn: () => fetchVaultPage(selectedStem!),
    enabled: selectedStem !== null && viewMode === "note",
  });

  const resolveStem = useMemo(
    () => makeStemResolver((graphQuery.data?.nodes ?? []).map((n) => n.id)),
    [graphQuery.data],
  );

  // Resolves a cited stem to its title + category so chat citation chips
  // carry the same colours as the vault graph legend -- same map vault.tsx
  // builds for the same reason.
  const nodeByStem = useMemo(() => {
    const map = new Map<string, { title: string; category: string }>();
    for (const n of graphQuery.data?.nodes ?? []) {
      map.set(n.id, { title: n.title, category: n.category });
    }
    return map;
  }, [graphQuery.data]);

  // Following a wikilink inside a note swaps the viewer to that page, whether
  // or not it's one of the papers in the list on the left -- same as clicking
  // a citation or a node does on /vault.
  const wikiLinkComponent = useMemo(
    () =>
      makeWikiLinkRenderer(resolveStem, (stem) => {
        setSelectedStem(stem);
        setViewMode("note");
      }),
    [resolveStem],
  );

  const papers = libraryQuery.data?.papers ?? [];
  const openPaper = (stem: string, mode: ViewMode) => {
    setSelectedStem(stem);
    setViewMode(mode);
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">
          Library{libraryQuery.data ? ` · ${papers.length} paper${papers.length === 1 ? "" : "s"}` : ""}
        </h1>
        <button
          onClick={() => setChatOpen(true)}
          className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
        >
          <MessageSquare className="h-3.5 w-3.5" />
          Chat with your library
        </button>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-4">
        {libraryQuery.isPending && (
          <p className="p-4 text-sm text-muted-foreground">Loading library…</p>
        )}

        {libraryQuery.isError && (
          <div className="flex items-start gap-3 rounded-xl border border-border bg-surface p-4">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />
            <div>
              <p className="text-sm font-medium text-foreground">Could not load the library</p>
              <p className="mt-1 text-xs text-muted-foreground">
                {(libraryQuery.error as Error).message}
              </p>
            </div>
          </div>
        )}

        {libraryQuery.data && papers.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <LibraryIcon className="h-5 w-5 text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              No papers yet. Add a page under wiki/sources/ with a `raw:` field pointing at
              its PDF.
            </p>
          </div>
        )}

        {papers.length > 0 && (
          <div className="flex h-full min-h-0 gap-4">
            {/* List pane */}
            <div className="flex min-h-0 w-full max-w-sm flex-col gap-2 overflow-y-auto rounded-xl border border-border bg-surface p-3">
              {papers.map((paper) => (
                <PaperListItem
                  key={paper.stem}
                  paper={paper}
                  active={selectedStem === paper.stem}
                  onOpen={(mode) => openPaper(paper.stem, mode)}
                />
              ))}
            </div>

            {/* Viewer pane */}
            <div className="min-h-0 flex-1 overflow-hidden rounded-xl border border-border bg-surface">
              {!selectedStem && (
                <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                  <FileText className="h-5 w-5 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">
                    Pick a paper's PDF or Note to read it here
                  </p>
                </div>
              )}

              {selectedStem && viewMode === "pdf" && (
                <div className="flex h-full flex-col">
                  <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
                    <a
                      href={rawPdfUrl(selectedStem)}
                      target="_blank"
                      rel="noreferrer"
                      className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                    >
                      <ExternalLink className="h-3.5 w-3.5" />
                      Open in new tab
                    </a>
                    <button
                      onClick={() => {
                        setSelectedStem(null);
                        setViewMode(null);
                      }}
                      className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                      aria-label="Close PDF"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                  <iframe
                    key={selectedStem}
                    src={rawPdfUrl(selectedStem)}
                    title={`PDF: ${selectedStem}`}
                    className="min-h-0 flex-1"
                  />
                </div>
              )}

              {selectedStem && viewMode === "note" && (
                <div ref={viewerScrollRef} className="h-full overflow-y-auto p-5">
                  {pageQuery.isPending && (
                    <p className="text-sm text-muted-foreground">Loading note…</p>
                  )}
                  {pageQuery.isError && (
                    <p className="text-sm text-destructive">
                      {(pageQuery.error as Error).message}
                    </p>
                  )}
                  {pageQuery.data && (
                    <article>
                      <div className="flex items-center justify-between gap-2">
                        <p className="font-mono text-xs text-muted-foreground">
                          {pageQuery.data.path}
                        </p>
                        <button
                          onClick={() => {
                            setSelectedStem(null);
                            setViewMode(null);
                          }}
                          className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                          aria-label="Close note"
                        >
                          <X className="h-4 w-4" />
                        </button>
                      </div>
                      <h2 className="mt-2 text-lg font-medium text-foreground">
                        {pageQuery.data.title}
                      </h2>
                      <PageMeta meta={pageQuery.data.meta} />
                      <div className="prose-clio mt-5 text-sm">
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkWikiLinks]}
                          urlTransform={wikiAwareUrlTransform}
                          components={{
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
              )}
            </div>
          </div>
        )}
      </div>

      {/* Slide-over library chat -- same pattern as vault.tsx's panel. */}
      {chatOpen && (
        <div className="fixed inset-0 z-50 flex">
          <div
            className="flex-1 bg-black/60 backdrop-blur-[2px]"
            onClick={() => setChatOpen(false)}
          />
          <div className="flex h-full w-full max-w-[480px] flex-col border-l border-border bg-background shadow-panel">
            <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-3">
              <div className="flex min-w-0 items-center gap-2">
                <h2 className="truncate text-sm font-medium">Chat with your library</h2>
                <span className="shrink-0 rounded-full bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground">
                  Grounded
                </span>
              </div>
              <button
                onClick={() => setChatOpen(false)}
                className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                aria-label="Close library chat"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <ChatSurface
                compact
                emptyTitle="Ask your library"
                emptySubtitle="Answers cite the wiki pages they came from. Click a citation to read it right here."
                suggestions={[
                  "What decides output safety in diffusion models?",
                  "Which claims are contested?",
                  "What does my wiki say about remasking?",
                ]}
                resolvePage={(stem) => nodeByStem.get(stem)}
                resolveStem={resolveStem}
                onCitationClick={(stem) => {
                  setSelectedStem(stem);
                  setViewMode("note");
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
