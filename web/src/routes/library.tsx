import { createFileRoute } from "@tanstack/react-router";
import { useMemo, useState } from "react";
import ReactMarkdown from "react-markdown";
import { MessageSquare, Search, X, Network, FileText } from "lucide-react";
import { paperNotes, noteById } from "@/lib/clio-data";
import { GraphView } from "@/components/clio/graph-view";
import { ChatSurface } from "@/components/clio/chat-surface";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/library")({
  head: () => ({
    meta: [
      { title: "Library — Clio research notes" },
      {
        name: "description",
        content:
          "Browse your read papers as markdown notes, explore the link graph, and chat with a library-grounded assistant.",
      },
      { property: "og:title", content: "Library — Clio research notes" },
      {
        property: "og:description",
        content: "Your read papers as markdown notes, a link graph, and a grounded chat.",
      },
    ],
  }),
  component: LibraryPage,
});

function LibraryPage() {
  const [view, setView] = useState<"notes" | "graph">("notes");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(paperNotes[0]!.id);
  const [chatOpen, setChatOpen] = useState(false);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return paperNotes;
    return paperNotes.filter(
      (n) =>
        n.title.toLowerCase().includes(q) ||
        n.authors.join(" ").toLowerCase().includes(q) ||
        n.tags.some((t) => t.includes(q)),
    );
  }, [query]);

  const selected = noteById(selectedId) ?? paperNotes[0]!;

  const select = (id: string) => {
    setSelectedId(id);
    setView("notes");
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">
          Library · {paperNotes.length} notes
        </h1>
        <div className="flex items-center gap-2">
          <div className="flex rounded-lg border border-border bg-surface p-0.5">
            {(["notes", "graph"] as const).map((v) => (
              <button
                key={v}
                onClick={() => setView(v)}
                className={cn(
                  "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                  view === v
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
              >
                {v === "notes" ? (
                  <FileText className="h-3.5 w-3.5" />
                ) : (
                  <Network className="h-3.5 w-3.5" />
                )}
                {v}
              </button>
            ))}
          </div>
          <button
            onClick={() => setChatOpen(true)}
            className="flex items-center gap-2 rounded-lg bg-primary px-3 py-2 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
          >
            <MessageSquare className="h-3.5 w-3.5" />
            Chat with your library
          </button>
        </div>
      </header>

      <div className="min-h-0 flex-1 overflow-hidden p-4">
        {view === "graph" ? (
          <GraphView onSelect={select} />
        ) : (
          <div className="flex h-full min-h-0 flex-col gap-4 lg:flex-row">
            {/* List pane */}
            <div className="flex min-h-0 flex-col rounded-xl border border-border bg-surface lg:w-2/5">
              <div className="border-b border-border p-3">
                <div className="flex items-center gap-2 rounded-lg bg-elevated px-3 py-2">
                  <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
                  <input
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    placeholder="Search titles, authors, tags…"
                    className="min-w-0 flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground/70"
                  />
                </div>
              </div>
              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {filtered.length === 0 && (
                  <p className="px-3 py-6 text-center text-sm text-muted-foreground">
                    No notes match “{query}”.
                  </p>
                )}
                {filtered.map((n) => (
                  <button
                    key={n.id}
                    onClick={() => setSelectedId(n.id)}
                    className={cn(
                      "mb-1 w-full rounded-lg border px-3 py-3 text-left transition-colors",
                      n.id === selectedId
                        ? "border-primary/70 bg-elevated"
                        : "border-transparent hover:bg-elevated/60",
                    )}
                  >
                    <p className="truncate text-sm font-medium text-foreground">{n.title}</p>
                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                      {n.authors.slice(0, 3).join(", ")} · {n.year}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {n.tags.slice(0, 3).map((t) => (
                        <span
                          key={t}
                          className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground"
                        >
                          {t}
                        </span>
                      ))}
                    </div>
                  </button>
                ))}
              </div>
            </div>

            {/* Note pane */}
            <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-border bg-surface p-6 lg:w-3/5">
              <h2 className="text-2xl font-semibold tracking-tight">{selected.title}</h2>
              <p className="mt-2 text-sm text-muted-foreground">
                {selected.authors.join(", ")} · {selected.year} · arXiv:{selected.arxivId}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {selected.tags.map((t) => (
                  <span
                    key={t}
                    className="rounded-full bg-secondary px-2 py-0.5 text-[11px] text-secondary-foreground"
                  >
                    {t}
                  </span>
                ))}
              </div>

              <div className="mt-6 rounded-lg border border-border bg-elevated/40 p-4">
                <p className="mb-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Abstract
                </p>
                <p className="text-sm leading-relaxed text-foreground/90">{selected.abstract}</p>
              </div>

              <div className="prose-clio mt-6 text-sm">
                <ReactMarkdown>{selected.notes}</ReactMarkdown>
              </div>

              <div className="mt-8 border-t border-border pt-5">
                <p className="mb-3 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                  Linked papers
                </p>
                <div className="flex flex-wrap gap-2">
                  {selected.linked.map((id) => {
                    const n = noteById(id);
                    if (!n) return null;
                    return (
                      <button
                        key={id}
                        onClick={() => setSelectedId(id)}
                        className="rounded-full border border-secondary/60 bg-elevated px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:border-primary hover:text-foreground"
                      >
                        {n.title}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Slide-over library chat */}
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
              {/* Chat is vault-grounded everywhere now, so citations are vault
                  page stems -- which this page has no viewer for. No
                  onCitationClick is passed, so chips render as plain labels
                  rather than buttons that go nowhere. Open /vault to read them. */}
              <ChatSurface
                compact
                emptyTitle="Ask your wiki"
                emptySubtitle="Answers cite the wiki pages they came from. Open Vault to read a cited page."
                suggestions={[
                  "What decides output safety in diffusion models?",
                  "Which claims are contested?",
                  "What does my wiki say about remasking?",
                ]}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
