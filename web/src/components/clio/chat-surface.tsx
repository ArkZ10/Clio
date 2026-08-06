import {
  ArrowUp,
  Clock,
  FileQuestion,
  Loader2,
  Plus,
  Sparkle,
  Trash2,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { cn } from "@/lib/utils";
import {
  colorForCategory,
  createChatSession,
  deleteChatSession,
  fetchChatSession,
  fetchChatSessions,
  streamVaultChat,
  type ChatSessionSummary,
  type ChatSurfaceName,
} from "@/lib/vault";
import { makeWikiLinkRenderer, remarkWikiLinks, wikiAwareUrlTransform } from "@/lib/wiki-links";

type ChatMessage = {
  id: string;
  role: "user" | "assistant";
  text: string;
  /** Assistant only: structured citations from the backend, not scraped prose. */
  citedPages?: string[] | undefined;
  selectedCount?: number | undefined;
  droppedCount?: number | undefined;
  noCoverage?: boolean | undefined;
};

let messageSeq = 0;
const nextId = () => `m${++messageSeq}`;

/** sqlite's CURRENT_TIMESTAMP is UTC but not ISO -- fix that up first. */
function relativeTime(sqliteTimestamp: string): string {
  const then = new Date(sqliteTimestamp.replace(" ", "T") + "Z").getTime();
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(then).toLocaleDateString();
}

export function ChatSurface({
  surface,
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
  /** Resolves a raw [[wikilink]] target to a real stem -- see lib/wiki-links.ts.
   *  Absent where there's no vault graph loaded, so links render as plain text. */
  resolveStem,
}: {
  surface: ChatSurfaceName;
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
  // True from submit until the "start" event names a message to stream into
  // -- gates the "Searching..." spinner, which should disappear the moment
  // there's an actual (even empty) assistant bubble to watch fill in.
  const [awaitingFirstToken, setAwaitingFirstToken] = useState(false);
  // How many pages selection found for the in-flight turn, from the
  // "selected" event -- lets the spinner say something more specific than
  // "Searching" during the model's hidden reasoning phase, which can run
  // 10-25s with nothing else to show for it.
  const [selectedCount, setSelectedCount] = useState<number | null>(null);
  const [waitedMs, setWaitedMs] = useState(0);
  // Which conversation this is, and whether the initial resume-lookup is
  // still in flight (backend/chat_store.py).
  const [sessionId, setSessionId] = useState<number | null>(null);
  const [resolving, setResolving] = useState(true);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [sessions, setSessions] = useState<ChatSessionSummary[] | null>(null);
  const [historyBusy, setHistoryBusy] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  // Inline [[wikilinks]] navigate the same place a citation chip click does.
  const wikiLinkComponent = useMemo(
    () => makeWikiLinkRenderer(resolveStem, onCitationClick),
    [resolveStem, onCitationClick],
  );

  // Resume the most recent session for this (surface, pageContext) bucket on
  // mount and whenever pageContext changes.
  useEffect(() => {
    let cancelled = false;
    setResolving(true);
    setSessionId(null);
    setMessages([]);
    setHistoryOpen(false);
    setSessions(null);

    void (async () => {
      try {
        const { sessions: list } = await fetchChatSessions(surface);
        const match = list.find((s) => s.page_context === pageContext);
        if (!match) {
          if (!cancelled) setResolving(false);
          return;
        }
        const detail = await fetchChatSession(match.id);
        if (cancelled) return;
        setSessionId(detail.id);
        setMessages(
          detail.messages.map((m) => ({
            id: nextId(),
            role: m.role,
            text: m.content,
            citedPages: m.cited_pages,
            selectedCount: m.selected_pages.length,
            droppedCount: m.dropped_count ?? undefined,
            noCoverage: m.no_coverage ?? undefined,
          })),
        );
      } catch {
        // Best-effort resume -- worst case it opens empty.
      } finally {
        if (!cancelled) setResolving(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [surface, pageContext]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, busy]);

  // Ticks while waiting for the first token, so the spinner visibly counts
  // up instead of sitting static for however long reasoning takes.
  useEffect(() => {
    if (!awaitingFirstToken) return;
    const start = Date.now();
    setWaitedMs(0);
    const id = setInterval(() => setWaitedMs(Date.now() - start), 250);
    return () => clearInterval(id);
  }, [awaitingFirstToken]);

  useEffect(() => {
    if (!busy && !resolving) inputRef.current?.focus();
  }, [busy, resolving]);

  const loadHistory = () => {
    setHistoryOpen((open) => !open);
    if (sessions === null) {
      setHistoryBusy(true);
      void fetchChatSessions(surface)
        .then((res) => setSessions(res.sessions))
        .catch(() => setSessions([]))
        .finally(() => setHistoryBusy(false));
    }
  };

  const openSession = (id: number) => {
    if (id === sessionId) {
      setHistoryOpen(false);
      return;
    }
    setResolving(true);
    setHistoryOpen(false);
    void fetchChatSession(id)
      .then((detail) => {
        setSessionId(detail.id);
        setMessages(
          detail.messages.map((m) => ({
            id: nextId(),
            role: m.role,
            text: m.content,
            citedPages: m.cited_pages,
            selectedCount: m.selected_pages.length,
            droppedCount: m.dropped_count ?? undefined,
            noCoverage: m.no_coverage ?? undefined,
          })),
        );
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load that conversation."))
      .finally(() => setResolving(false));
  };

  const startNewChat = () => {
    setSessionId(null);
    setMessages([]);
    setError(null);
    setHistoryOpen(false);
  };

  const removeSession = (id: number) => {
    void deleteChatSession(id).then(() => {
      setSessions((prev) => prev?.filter((s) => s.id !== id) ?? null);
      if (id === sessionId) startNewChat();
    });
  };

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || busy || resolving) return;
    setError(null);
    setInput("");

    setMessages((prev) => [...prev, { id: nextId(), role: "user", text: value }]);
    setBusy(true);
    setAwaitingFirstToken(true);
    setSelectedCount(null);

    void (async () => {
      let assistantId: string | null = null;
      try {
        let sid = sessionId;
        if (sid === null) {
          const created = await createChatSession(surface, pageContext);
          sid = created.id;
          setSessionId(sid);
          setSessions(null); // invalidate the cached history list
        }

        for await (const event of streamVaultChat({
          question: value,
          page_context: pageContext,
          session_id: sid,
        })) {
          if (event.type === "selected") {
            setSelectedCount(event.selected_pages.length);
          } else if (event.type === "start") {
            const id = nextId();
            assistantId = id;
            setAwaitingFirstToken(false);
            setMessages((prev) => [
              ...prev,
              {
                id,
                role: "assistant",
                text: "",
                citedPages: event.cited_pages,
                selectedCount: event.selected_pages.length,
                droppedCount: event.dropped_count,
                noCoverage: event.no_coverage,
              },
            ]);
          } else if (event.type === "delta") {
            const id = assistantId;
            if (id) {
              setMessages((prev) =>
                prev.map((m) => (m.id === id ? { ...m, text: m.text + event.text } : m)),
              );
            }
          } else if (event.type === "error") {
            throw new Error(event.detail);
          }
        }
        setError(null);
      } catch (e) {
        // A partial or never-started bubble from this turn shouldn't linger
        // next to the error banner that now explains what happened.
        if (assistantId) {
          const id = assistantId;
          setMessages((prev) => prev.filter((m) => m.id !== id || m.text));
        }
        setError(
          e instanceof Error ? e.message : "Something went wrong. Please try again.",
        );
      } finally {
        setBusy(false);
        setAwaitingFirstToken(false);
      }
    })();
  };

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="relative flex items-center justify-between gap-2 border-b border-border px-4 py-2">
        <button
          onClick={loadHistory}
          className={cn(
            "flex items-center gap-1.5 rounded-md px-2 py-1 text-xs transition-colors",
            historyOpen
              ? "bg-elevated text-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <Clock className="h-3.5 w-3.5" />
          History
        </button>
        <button
          onClick={startNewChat}
          disabled={sessionId === null && messages.length === 0}
          className="flex items-center gap-1.5 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
        >
          <Plus className="h-3.5 w-3.5" />
          New chat
        </button>

        {historyOpen && (
          <div className="absolute top-full left-0 z-10 mt-1 max-h-80 w-full overflow-y-auto rounded-lg border border-border bg-surface shadow-panel">
            {historyBusy && (
              <p className="p-3 text-xs text-muted-foreground">Loading history…</p>
            )}
            {sessions !== null && sessions.length === 0 && (
              <p className="p-3 text-xs text-muted-foreground">No past conversations yet.</p>
            )}
            {sessions?.map((s) => (
              <div key={s.id} className="flex items-center gap-1 border-b border-border/60 last:border-0">
                <button
                  onClick={() => openSession(s.id)}
                  className={cn(
                    "min-w-0 flex-1 px-3 py-2 text-left transition-colors hover:bg-elevated",
                    s.id === sessionId && "bg-elevated",
                  )}
                >
                  <p className="truncate text-xs text-foreground">{s.title}</p>
                  <p className="mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground">
                    {s.page_context && (
                      <span className="truncate rounded-full bg-secondary/50 px-1.5 py-0.5">
                        {s.page_context}
                      </span>
                    )}
                    {relativeTime(s.updated_at)}
                  </p>
                </button>
                <button
                  onClick={() => removeSession(s.id)}
                  aria-label="Delete conversation"
                  className="shrink-0 p-2 text-muted-foreground transition-colors hover:text-destructive"
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className={cn("mx-auto w-full px-4 py-6", compact ? "max-w-full" : "max-w-[760px]")}>
          {resolving ? (
            <div
              className={cn(
                "flex items-center justify-center gap-2 text-sm text-muted-foreground",
                compact ? "py-10" : "min-h-[55vh]",
              )}
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              Loading conversation…
            </div>
          ) : messages.length === 0 ? (
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
                        // Must not read as a normal answer.
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
                          // Only a button where there's somewhere to go.
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

              {awaitingFirstToken && (
                <div className="flex items-center gap-2 pl-1 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  {selectedCount ? (
                    <span>
                      Found {selectedCount} page{selectedCount === 1 ? "" : "s"}, thinking…
                    </span>
                  ) : (
                    <span>Searching your wiki…</span>
                  )}
                  {waitedMs >= 1000 && (
                    <span className="font-mono text-[11px] text-muted-foreground/70">
                      {Math.floor(waitedMs / 1000)}s
                    </span>
                  )}
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
              disabled={resolving}
              placeholder={
                pageContext ? `Ask about ${pageContext}…` : "Ask your wiki…"
              }
              className="max-h-40 min-h-9 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm text-foreground outline-none placeholder:text-muted-foreground/70 disabled:opacity-60"
            />
            <button
              type="submit"
              disabled={busy || resolving || !input.trim()}
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
