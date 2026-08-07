import { createFileRoute } from "@tanstack/react-router";
import { useServerFn } from "@tanstack/react-start";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, ExternalLink, FileText, Search, X } from "lucide-react";
import { ARXIV_FOUNDING_YEAR, searchArxiv, type ArxivPaper } from "@/lib/arxiv.functions";
import { cn } from "@/lib/utils";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

export const Route = createFileRoute("/explore")({
  head: () => ({
    meta: [
      { title: "Explore — Discover arXiv papers with Clio" },
      {
        name: "description",
        content:
          "Search arXiv from Clio and get a list of relevant papers with abstracts and one-click saving.",
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
const CURRENT_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from(
  { length: CURRENT_YEAR - ARXIV_FOUNDING_YEAR + 1 },
  (_, i) => CURRENT_YEAR - i,
);

type ViewMode = "abstract" | "pdf";

const absUrl = (paper: ArxivPaper) => `https://arxiv.org/abs/${paper.id}`;

function ExplorePage() {
  const [query, setQuery] = useState("");
  // What's actually been searched, distinct from the input's live text --
  // typing a new draft without submitting must not affect pagination of the
  // current results.
  const [activeQuery, setActiveQuery] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  // Unlike the query text, a year filter change applies immediately (no
  // separate "submit" step) -- it's a bounded dropdown pick, not something
  // you're mid-typing.
  const [fromYear, setFromYear] = useState<number | null>(null);
  const [toYear, setToYear] = useState<number | null>(null);
  // Set by clicking a title (abstract) or "Open PDF" (pdf) -- switches into
  // the split list+viewer layout, same pattern as /library's Note/PDF modes.
  // Cleared by the viewer's close button.
  const [viewingPaper, setViewingPaper] = useState<ArxivPaper | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>("abstract");
  const run = useServerFn(searchArxiv);
  const resultsTopRef = useRef<HTMLDivElement>(null);

  const openPaper = (p: ArxivPaper, mode: ViewMode) => {
    setViewingPaper(p);
    setViewMode(mode);
  };

  const search = useQuery({
    queryKey: ["explore", activeQuery, page, fromYear, toYear],
    queryFn: () =>
      run({
        data: {
          query: activeQuery!,
          start: (page - 1) * PAGE_SIZE,
          maxResults: PAGE_SIZE,
          fromYear: fromYear ?? undefined,
          toYear: toYear ?? undefined,
        },
      }),
    enabled: activeQuery !== null,
  });

  const applyYearFilter = (bound: "from" | "to", value: string) => {
    const year = value === "any" ? null : Number(value);
    if (bound === "from") setFromYear(year);
    else setToYear(year);
    setPage(1);
  };

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
    <div className="flex h-full min-h-0 flex-col">
      <div className="mx-auto w-full max-w-3xl px-5 pt-10">
        <div ref={resultsTopRef} />
        <h1 className="text-center text-2xl font-semibold tracking-tight">
          What do you want to explore?
        </h1>
        <p className="mt-2 text-center text-sm text-muted-foreground">
          Search arXiv, sorted by relevance to your question.
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

        <div className="mt-3 flex items-center justify-center gap-2 text-xs text-muted-foreground">
          <span>Year</span>
          <Select
            value={fromYear !== null ? String(fromYear) : "any"}
            onValueChange={(v) => applyYearFilter("from", v)}
          >
            <SelectTrigger
              aria-label="From year"
              className="h-auto w-auto gap-1.5 rounded-lg border-border bg-elevated px-2.5 py-1.5 text-xs"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              {YEAR_OPTIONS.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span>to</span>
          <Select
            value={toYear !== null ? String(toYear) : "any"}
            onValueChange={(v) => applyYearFilter("to", v)}
          >
            <SelectTrigger
              aria-label="To year"
              className="h-auto w-auto gap-1.5 rounded-lg border-border bg-elevated px-2.5 py-1.5 text-xs"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="any">Any</SelectItem>
              {YEAR_OPTIONS.map((y) => (
                <SelectItem key={y} value={String(y)}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      </div>

      <div className="mt-6 min-h-0 flex-1 overflow-hidden px-5 pb-10">
        {activeQuery === null && (
          <div className="mx-auto max-w-3xl py-8 text-center">
            <p className="text-sm text-muted-foreground">
              Start with a topic, a method, or an open question.
            </p>
            <ExampleButtons onPick={submit} />
          </div>
        )}

        {activeQuery !== null && search.isPending && (
          <div className="mx-auto max-w-3xl">
            <SkeletonList />
          </div>
        )}

        {activeQuery !== null && !search.isPending && search.isError && (
          <p className="mx-auto max-w-3xl rounded-xl border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
            arXiv search failed. Please try again in a moment.
          </p>
        )}

        {activeQuery !== null &&
          !search.isPending &&
          !search.isError &&
          results.length === 0 && (
            <div className="mx-auto max-w-3xl py-8 text-center">
              <p className="text-sm text-muted-foreground">
                No papers matched that query. Try broader terms.
              </p>
              <ExampleButtons onPick={submit} />
            </div>
          )}

        {results.length > 0 && viewingPaper === null && (
          <div className="mx-auto h-full max-w-3xl overflow-y-auto">
            <p className="mb-3 text-xs text-muted-foreground">
              {totalResults.toLocaleString()} result{totalResults === 1 ? "" : "s"}
            </p>
            <div className="space-y-3">
              {results.map((p, i) => (
                <article
                  key={p.id + i}
                  onClick={() => openPaper(p, "abstract")}
                  className="group cursor-pointer rounded-xl border border-border bg-surface p-4 transition-colors hover:border-secondary"
                >
                  <div className="flex gap-4">
                    <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">
                      {(page - 1) * PAGE_SIZE + i + 1}
                    </span>
                    <div className="min-w-0 flex-1">
                      <h2 className="text-sm font-semibold text-foreground group-hover:underline">
                        {p.title}
                      </h2>
                      <p className="mt-1 truncate text-xs text-muted-foreground">
                        {p.authors.slice(0, 4).join(", ")}
                        {p.authors.length > 4 ? " et al." : ""} · {p.year} · arXiv:{p.id}
                      </p>
                      <p className="mt-2 line-clamp-3 text-sm leading-relaxed text-foreground/80">
                        {p.summary}
                      </p>
                      <div className="mt-3 hidden flex-wrap gap-2 group-focus-within:flex group-hover:flex max-md:flex">
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            openPaper(p, "pdf");
                          }}
                          className="flex items-center gap-1.5 rounded-lg border border-border bg-elevated px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
                        >
                          <FileText className="h-3.5 w-3.5" />
                          Open PDF
                        </button>
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
          </div>
        )}

        {results.length > 0 && viewingPaper !== null && (
          <div className="flex h-full min-h-0 gap-4">
            {/* List pane */}
            <div className="flex min-h-0 w-full max-w-sm flex-col gap-2 overflow-y-auto rounded-xl border border-border bg-surface p-3">
              <p className="px-1 text-xs text-muted-foreground">
                {totalResults.toLocaleString()} result{totalResults === 1 ? "" : "s"}
              </p>
              {results.map((p, i) => (
                <button
                  key={p.id + i}
                  onClick={() => openPaper(p, "abstract")}
                  className={cn(
                    "rounded-lg border p-3 text-left transition-colors",
                    p.id === viewingPaper.id
                      ? "border-primary/70 bg-elevated"
                      : "border-transparent hover:bg-elevated/60",
                  )}
                >
                  <h2 className="text-sm font-medium text-foreground">{p.title}</h2>
                  <p className="mt-1 truncate text-xs text-muted-foreground">
                    {p.authors.slice(0, 3).join(", ")}
                    {p.authors.length > 3 ? " et al." : ""} · {p.year}
                  </p>
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openPaper(p, "pdf");
                      }}
                      className={cn(
                        "flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-xs transition-colors",
                        p.id === viewingPaper.id && viewMode === "pdf"
                          ? "border-border bg-background text-foreground"
                          : "border-border bg-elevated text-muted-foreground hover:text-foreground",
                      )}
                    >
                      <FileText className="h-3.5 w-3.5" />
                      PDF
                    </button>
                  </div>
                </button>
              ))}

              <div className="mt-1 flex items-center justify-between gap-2 px-1 pt-1">
                <button
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || search.isFetching}
                  className="flex items-center gap-1 rounded-lg border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  <ChevronLeft className="h-3 w-3" />
                  Prev
                </button>
                <p className="text-[11px] text-muted-foreground">
                  {page} / {totalPages.toLocaleString()}
                </p>
                <button
                  onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                  disabled={page >= totalPages || search.isFetching}
                  className="flex items-center gap-1 rounded-lg border border-border bg-elevated px-2 py-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
                >
                  Next
                  <ChevronRight className="h-3 w-3" />
                </button>
              </div>
            </div>

            {/* Viewer pane */}
            <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
              <div className="flex items-center justify-between gap-2 border-b border-border px-4 py-2.5">
                <div className="flex min-w-0 items-center gap-3">
                  <p className="truncate text-xs text-muted-foreground">{viewingPaper.title}</p>
                  <div className="flex shrink-0 items-center gap-1 rounded-lg border border-border bg-elevated p-0.5">
                    <button
                      onClick={() => setViewMode("abstract")}
                      className={cn(
                        "rounded-md px-2 py-1 text-[11px] transition-colors",
                        viewMode === "abstract"
                          ? "bg-background text-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      Abstract
                    </button>
                    <button
                      onClick={() => setViewMode("pdf")}
                      className={cn(
                        "rounded-md px-2 py-1 text-[11px] transition-colors",
                        viewMode === "pdf"
                          ? "bg-background text-foreground"
                          : "text-muted-foreground hover:text-foreground",
                      )}
                    >
                      PDF
                    </button>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <a
                    href={viewMode === "abstract" ? absUrl(viewingPaper) : viewingPaper.pdfUrl}
                    target="_blank"
                    rel="noreferrer"
                    className="flex items-center gap-1.5 text-xs text-muted-foreground transition-colors hover:text-foreground"
                  >
                    <ExternalLink className="h-3.5 w-3.5" />
                    {viewMode === "abstract" ? "View on arXiv" : "Open in new tab"}
                  </a>
                  <button
                    onClick={() => setViewingPaper(null)}
                    className="rounded-md p-1.5 text-muted-foreground transition-colors hover:bg-elevated hover:text-foreground"
                    aria-label="Close"
                  >
                    <X className="h-4 w-4" />
                  </button>
                </div>
              </div>

              {viewMode === "abstract" ? (
                <div className="min-h-0 flex-1 overflow-y-auto p-6">
                  <h2 className="text-lg font-semibold leading-snug text-foreground">
                    {viewingPaper.title}
                  </h2>
                  <p className="mt-2 text-sm text-muted-foreground">
                    {viewingPaper.authors.join(", ")}
                  </p>
                  <p className="mt-1 text-xs text-muted-foreground">
                    {viewingPaper.year} · arXiv:{viewingPaper.id}
                  </p>

                  {viewingPaper.categories.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1.5">
                      {viewingPaper.categories.map((c) => (
                        <span
                          key={c}
                          className="rounded-full border border-border bg-elevated px-2 py-0.5 text-[11px] text-muted-foreground"
                        >
                          {c}
                        </span>
                      ))}
                    </div>
                  )}

                  <p className="mt-5 whitespace-pre-line text-sm leading-relaxed text-foreground/90">
                    {viewingPaper.summary}
                  </p>

                  <div className="mt-5 space-y-1 text-xs text-muted-foreground">
                    {viewingPaper.comment && <p>Comment: {viewingPaper.comment}</p>}
                    {viewingPaper.journalRef && <p>Journal ref: {viewingPaper.journalRef}</p>}
                    {viewingPaper.doi && <p>DOI: {viewingPaper.doi}</p>}
                  </div>

                  <button
                    onClick={() => setViewMode("pdf")}
                    className="mt-6 flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90"
                  >
                    <FileText className="h-3.5 w-3.5" />
                    Open PDF
                  </button>
                </div>
              ) : (
                <iframe
                  key={viewingPaper.id}
                  src={viewingPaper.pdfUrl}
                  title={`PDF: ${viewingPaper.title}`}
                  className="min-h-0 flex-1"
                />
              )}
            </div>
          </div>
        )}
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
