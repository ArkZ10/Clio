import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import {
  BookmarkPlus,
  Check,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Search,
} from "lucide-react";
import { searchArxiv } from "@/lib/arxiv.functions";
import { cn } from "@/lib/utils";

export const Route = createFileRoute("/explore")({
  head: () => ({
    meta: [
      { title: "Explore — Discover arXiv papers with Clio" },
      {
        name: "description",
        content:
          "Search arXiv from Clio and get a ranked list of relevant papers with abstracts, relevance scores, and one-click saving.",
      },
      { property: "og:title", content: "Explore — Discover arXiv papers with Clio" },
      {
        property: "og:description",
        content: "Search arXiv and get ranked, readable results inside Clio.",
      },
    ],
  }),
  component: ExplorePage,
});

const EXAMPLES = [
  "sparse mixture of experts routing",
  "long-context retrieval evaluation",
  "diffusion model distillation",
  "mechanistic interpretability of induction heads",
];

const PAGE_SIZE = 10;

function ExplorePage() {
  const [query, setQuery] = useState("");
  // What's actually been searched, distinct from the input's live text --
  // typing a new draft without submitting must not affect pagination of the
  // current results.
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [saved, setSaved] = useState<string[]>([]);
  const run = useServerFn(searchArxiv);
  const resultsTopRef = useRef<HTMLDivElement>(null);

  const search = useQuery({
    queryKey: ["explore", activeQuery, page],
    queryFn: () =>
      run({
        data: { query: activeQuery!, start: (page - 1) * PAGE_SIZE, maxResults: PAGE_SIZE },
      }),
    enabled: activeQuery !== null,
  });

  useEffect(() => {
    resultsTopRef.current?.scrollIntoView({ block: "start" });
  }, [page, activeQuery]);

  const submit = (q: string) => {
    const value = q.trim();
    if (!value) return;
    setQuery(value);
    setActiveQuery(value);
    setPage(1);
  };

  const results = search.data?.papers ?? [];
  const totalResults = search.data?.totalResults ?? 0;
  const totalPages = Math.max(1, Math.ceil(totalResults / PAGE_SIZE));

  return (
    <div className="h-full min-h-0 overflow-y-auto">
      <div className="mx-auto w-full max-w-3xl px-5 py-10">
        <div ref={resultsTopRef} />
        <h1 className="text-center text-2xl font-semibold tracking-tight">
          What do you want to explore?
        </h1>
        <p className="mt-2 text-center text-sm text-muted-foreground">
          Search arXiv and rank results by relevance to your question.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit(query);
          }}
          className="mt-6 flex items-center gap-2 rounded-xl border border-border bg-elevated p-2 focus-within:border-primary"
        >
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="e.g. efficient attention for long sequences"
            className="min-w-0 flex-1 bg-transparent px-3 py-2 text-sm outline-none placeholder:text-muted-foreground/70"
          />
          <button
            type="submit"
            disabled={search.isFetching || !query.trim()}
            className="flex shrink-0 items-center gap-2 rounded-lg bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
          >
            <Search className="h-4 w-4" />
            <span className="hidden sm:inline">Search</span>
          </button>
        </form>

        <div className="mt-10">
          {activeQuery === null && (
            <div className="py-8 text-center">
              <p className="text-sm text-muted-foreground">
                Start with a topic, a method, or an open question.
              </p>
              <ExampleButtons onPick={submit} />
            </div>
          )}

          {activeQuery !== null && search.isPending && <SkeletonList />}

          {activeQuery !== null && !search.isPending && search.isError && (
            <p className="rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              arXiv search failed. Please try again in a moment.
            </p>
          )}

          {activeQuery !== null &&
            !search.isPending &&
            !search.isError &&
            results.length === 0 && (
              <div className="py-8 text-center">
                <p className="text-sm text-muted-foreground">
                  No papers matched that query. Try broader terms.
                </p>
                <ExampleButtons onPick={submit} />
              </div>
            )}

          {results.length > 0 && (
            <>
              <p className="mb-3 text-xs text-muted-foreground">
                {totalResults.toLocaleString()} result{totalResults === 1 ? "" : "s"}
              </p>
              <div className="space-y-3">
                {results.map((p, i) => (
                  <article
                    key={p.id + i}
                    className="group rounded-xl border border-border bg-surface p-4 transition-colors hover:border-secondary"
                  >
                    <div className="flex gap-4">
                      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                        {(page - 1) * PAGE_SIZE + i + 1}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <h2 className="min-w-0 flex-1 text-sm font-semibold text-foreground">
                            {p.title}
                          </h2>
                          <span className="shrink-0 rounded-full border border-secondary/60 bg-elevated px-2 py-0.5 text-[11px] text-muted-foreground">
                            {(p.score * 100).toFixed(0)}% match
                          </span>
                        </div>
                        <p className="mt-1 truncate text-xs text-muted-foreground">
                          {p.authors.slice(0, 4).join(", ")}
                          {p.authors.length > 4 ? " et al." : ""} · {p.year} · arXiv:{p.id}
                        </p>
                        <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-foreground/80">
                          {p.summary}
                        </p>
                        <div className="mt-3 hidden flex-wrap gap-2 group-focus-within:flex group-hover:flex max-md:flex">
                          <button
                            onClick={() =>
                              setSaved((s) => (s.includes(p.id) ? s : [...s, p.id]))
                            }
                            className={cn(
                              "flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-xs font-medium transition-colors",
                              saved.includes(p.id)
                                ? "bg-secondary text-secondary-foreground"
                                : "bg-primary text-primary-foreground hover:opacity-90",
                            )}
                          >
                            {saved.includes(p.id) ? (
                              <Check className="h-3.5 w-3.5" />
                            ) : (
                              <BookmarkPlus className="h-3.5 w-3.5" />
                            )}
                            {saved.includes(p.id) ? "Saved" : "Save to Library"}
                          </button>
                          <a
                            href={p.pdfUrl}
                            target="_blank"
                            rel="noreferrer"
                            className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                          >
                            <ExternalLink className="h-3.5 w-3.5" />
                            Open PDF
                          </a>
                        </div>
                      </div>
                    </div>
                  </article>
                ))}
              </div>

              <div className="mt-6 flex items-center justify-between gap-3">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || search.isFetching}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                  Prev
                </button>
                <p className="text-xs text-muted-foreground">
                  Page {page} of {totalPages.toLocaleString()}
                </p>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || search.isFetching}
                  className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 py-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  Next
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function ExampleButtons({ onPick }: { onPick: (q: string) => void }) {
  return (
    <div className="mt-5 flex flex-wrap justify-center gap-2">
      {EXAMPLES.map((e) => (
        <button
          key={e}
          onClick={() => onPick(e)}
          className="rounded-xl border border-border bg-surface px-3.5 py-2 text-sm text-muted-foreground transition-colors hover:border-secondary hover:bg-elevated hover:text-foreground"
        >
          {e}
        </button>
      ))}
    </div>
  );
}

function SkeletonList() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="shimmer rounded-xl border border-border bg-surface p-4">
          <div className="flex gap-4">
            <div className="h-8 w-8 shrink-0 rounded-full bg-elevated" />
            <div className="flex-1 space-y-2.5">
              <div className="h-3.5 w-3/4 rounded bg-elevated" />
              <div className="h-2.5 w-1/3 rounded bg-elevated/70" />
              <div className="h-2.5 w-full rounded bg-elevated/50" />
              <div className="h-2.5 w-5/6 rounded bg-elevated/50" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
