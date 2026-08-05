import { ArrowUp, Loader2, Sparkle, FileQuestion } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import { colorForCategory, postVaultChat, type ChatTurn } from "@/lib/vault";
import { makeWikiLinkRenderer, remarkWikiLinks, wikiAwareUrlTransform } from "@/lib/wiki-links";

/** Turns kept for follow-up questions ("what about the second one?"). Sent to
 *  the backend, which uses them ONLY for answering -- page selection always
 *  runs on the current question alone, so history can't bias retrieval. */
const HISTORY_TURNS = 6;

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Assistant only: structured citations from the backend, not scraped prose. */
  citedPages?: string[];
  selectedCount?: number;
  droppedCount?: number;
  noCoverage?: boolean;
};

let messageSeq = 0;
const nextId = () => `m${++messageSeq}`;

export function ChatSurface({
  suggestions,
  emptyTitle = "Ask me anything",
  emptySubtitle,
  onCitationClick,
  compact = false,
  /** Page stem to always ground this conversation in (the node-click flow). */
  pageContext = null,
  /** Resolves a page stem to a display label + category colour, so chips match
   *  the graph legend. Falls back to the raw stem when absent. */
  resolvePage,
  /** Resolves a raw [[wikilink]] target (the model cites inline, same [[Page]]
   *  form as citations) to a real stem -- see lib/wiki-links.ts. Absent on
   *  pages with no vault graph loaded (`/`, `/library`), where inline
   *  wikilinks in an answer render as plain text instead of a dead link. */
  resolveStem,
}: {
  suggestions: string[];
  emptyTitle?: string;
  emptySubtitle?: string;
  onCitationClick?: (stem: string) => void;
  compact?: boolean;
  pageContext?: string | null;
  resolvePage?: (stem: string) => { title: string; category: string } | undefined;
  resolveStem?: (target: string) => string | null;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Inline [[wikilinks]] in an answer navigate the same place a citation chip
  // click does -- both mean "go read that page".
  const wikiLinkComponent = useMemo(
    () => makeWikiLinkRenderer(resolveStem, onCitationClick),
    [resolveStem, onCitationClick],
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    if (!busy) inputRef.current?.focus();
  }, [busy]);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || busy) return;
    setError(null);
    setInput("");

    const history: ChatTurn[] = messages
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.text }));

    setMessages((prev) => [...prev, { id: nextId(), role: "user", text: value }]);
    setBusy(true);

    void (async () => {
      try {
        const res = await postVaultChat({
          question: value,
          page_context: pageContext,
          history,
        });
        setMessages((prev) => [
          ...prev,
          {
            id: nextId(),
            role: "assistant",
            text: res.answer,
            citedPages: res.cited_pages,
            selectedCount: res.selected_pages.length,
            droppedCount: res.dropped_count,
            noCoverage: res.no_coverage,
          },
        ]);
        // Clear on success -- the old implementation left a stale error banner
        // sitting under later successful answers.
        setError(null);
      } catch (e) {
        setError(
          e instanceof Error ? e.message : "Something went wrong. Please try again.",
        );
      } finally {
        setBusy(false);
      }
    })();
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("mx-auto w-full px-4 py-6", compact ? "max-w-full" : "max-w-[760px]")}>
          {messages.length === 0 ? (
            <div
              className={cn(
                "flex flex-col items-center justify-center text-center",
                compact ? "py-10" : "min-h-[55vh]",
              )}
            >
              <h2 className="text-2xl font-semibold tracking-tight">{emptyTitle}</h2>
              {emptySubtitle && (
                <p className="mt-2 max-w-md text-sm text-muted-foreground">{emptySubtitle}</p>
              )}
              <div className="mt-7 flex flex-wrap justify-center gap-2">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    onClick={() => submit(s)}
                    className="rounded-xl border border-border bg-surface px-3.5 py-2 text-sm text-muted-foreground transition-colors hover:border-secondary hover:bg-elevated hover:text-foreground"
                  >
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {messages.map((message) => {
                if (message.role === "user") {
                  return (
                    <div key={message.id} className="flex justify-end">
                      <div className="max-w-[85%] rounded-xl rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground">
                        {message.text}
                      </div>
                    </div>
                  );
                }
                const cited = message.citedPages ?? [];
                return (
                  <div key={message.id} className="flex flex-col items-start gap-2">
                    <div
                      className={cn(
                        "max-w-[95%] rounded-xl rounded-bl-sm border px-4 py-3",
                        // A no-coverage reply must NOT read as a normal answer.
                        message.noCoverage
                          ? "border-dashed border-muted-foreground/40 bg-background"
                          : "border-border bg-surface",
                      )}
                    >
                      {message.noCoverage && (
                        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                          <FileQuestion className="h-3.5 w-3.5" />
                          Not in your wiki
                        </p>
                      )}
                      <div
                        className={cn(
                          "prose-clio text-sm",
                          message.noCoverage && "text-muted-foreground",
                        )}
                      >
                        <ReactMarkdown
                          remarkPlugins={[remarkGfm, remarkWikiLinks]}
                          urlTransform={wikiAwareUrlTransform}
                          components={{ a: wikiLinkComponent }}
                        >
                          {message.text}
                        </ReactMarkdown>
                      </div>
                    </div>

                    {cited.length > 0 && (
                      <div className="flex flex-wrap gap-2 pl-1">
                        {cited.map((stem) => {
                          const page = resolvePage?.(stem);
                          const dot = page && (
                            <span
                              className="inline-block h-2 w-2 shrink-0 rounded-full"
                              style={{ backgroundColor: colorForCategory(page.category) }}
                            />
                          );
                          const label = <span className="truncate">{page?.title ?? stem}</span>;
                          const base =
                            "flex max-w-[240px] items-center gap-1.5 rounded-full border border-secondary/60 bg-elevated px-2.5 py-1 text-xs text-muted-foreground";
                          // Only a button where there is somewhere to go. On
                          // pages with no vault viewer the chip still shows what
                          // grounded the answer, without pretending to be
                          // clickable.
                          return onCitationClick ? (
                            <button
                              key={stem}
                              onClick={() => onCitationClick(stem)}
                              className={cn(base, "transition-colors hover:text-foreground")}
                            >
                              {dot}
                              {label}
                            </button>
                          ) : (
                            <span key={stem} className={base}>
                              {dot}
                              {label}
                            </span>
                          );
                        })}
                      </div>
                    )}

                    {/* Data-honesty line, same spirit as the graph's stats. */}
                    {message.selectedCount !== undefined && !message.noCoverage && (
                      <p className="pl-1 font-mono text-[11px] text-muted-foreground/70">
                        {message.selectedCount} page
                        {message.selectedCount === 1 ? "" : "s"} used
                        {message.droppedCount ? ` · ${message.droppedCount} dropped` : ""}
                      </p>
                    )}
                  </div>
                );
              })}

              {busy && (
                <div className="flex items-center gap-2 pl-1 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Searching your wiki…
                </div>
              )}
              <div ref={bottomRef} />
            </div>
          )}

          {error && (
            <p className="mt-4 rounded-lg border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {error}
            </p>
          )}
        </div>
      </div>

      <div className="border-t border-border bg-background/80 backdrop-blur">
        <div className={cn("mx-auto w-full px-4 py-4", compact ? "max-w-full" : "max-w-[760px]")}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(input);
            }}
            className="flex items-end gap-2 rounded-xl border border-border bg-elevated p-2 focus-within:border-primary"
          >
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(input);
                }
              }}
              placeholder={
                pageContext ? `Ask about ${pageContext}…` : "Ask your wiki…"
              }
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/70"
            />
            <button
              type="submit"
              disabled={busy || !input.trim()}
              className="grid h-9 w-9 shrink-0 place-items-center rounded-lg bg-primary text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
              aria-label="Send message"
            >
              {busy ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <ArrowUp className="h-4 w-4" />
              )}
            </button>
          </form>
          <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
            <Sparkle className="h-3 w-3" />
            {pageContext
              ? `Grounded in your wiki, always including “${pageContext}”.`
              : "Answers are grounded in your wiki pages only."}
          </p>
        </div>
      </div>
    </div>
  );
}
