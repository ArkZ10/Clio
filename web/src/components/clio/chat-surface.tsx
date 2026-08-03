import { useChat } from "@ai-sdk/react";
import { DefaultChatTransport, type UIMessage } from "ai";
import { ArrowUp, Loader2, Sparkle } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";
import { noteById } from "@/lib/clio-data";

function messageText(message: UIMessage) {
  return message.parts
    .map((part) => (part.type === "text" ? part.text : ""))
    .join("")
    .trim();
}

function citationsFrom(text: string) {
  const ids = new Set<string>();
  for (const match of text.matchAll(/\[([a-z0-9-]+)\]/g)) {
    const id = match[1];
    if (id && noteById(id)) ids.add(id);
  }
  return [...ids];
}

export function ChatSurface({
  mode = "general",
  suggestions,
  emptyTitle = "Ask me anything",
  emptySubtitle,
  onCitationClick,
  compact = false,
}: {
  mode?: "general" | "library";
  suggestions: string[];
  emptyTitle?: string;
  emptySubtitle?: string;
  onCitationClick?: (id: string) => void;
  compact?: boolean;
}) {
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const { messages, sendMessage, status } = useChat({
    id: `clio-${mode}`,
    transport: new DefaultChatTransport({
      api: "/api/chat",
      body: { mode },
    }),
    onError: (e) => setError(e.message || "Something went wrong. Please try again."),
  });

  const busy = status === "submitted" || status === "streaming";

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, status]);

  useEffect(() => {
    if (!busy) inputRef.current?.focus();
  }, [busy]);

  const submit = (text: string) => {
    const value = text.trim();
    if (!value || busy) return;
    setError(null);
    setInput("");
    void sendMessage({ text: value });
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
                const text = messageText(message);
                if (message.role === "user") {
                  return (
                    <div key={message.id} className="flex justify-end">
                      <div className="max-w-[85%] rounded-xl rounded-br-sm bg-primary px-4 py-2.5 text-sm leading-relaxed text-primary-foreground">
                        {text}
                      </div>
                    </div>
                  );
                }
                const citations = mode === "library" ? citationsFrom(text) : [];
                return (
                  <div key={message.id} className="flex flex-col items-start gap-2">
                    <div className="max-w-[95%] rounded-xl rounded-bl-sm border border-border bg-surface px-4 py-3">
                      <div className="prose-clio text-sm">
                        <ReactMarkdown>{text}</ReactMarkdown>
                      </div>
                    </div>
                    {citations.length > 0 && (
                      <div className="flex flex-wrap gap-2 pl-1">
                        {citations.map((id) => (
                          <button
                            key={id}
                            onClick={() => onCitationClick?.(id)}
                            className="max-w-[240px] truncate rounded-full border border-secondary/60 bg-elevated px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:text-foreground"
                          >
                            {noteById(id)?.title ?? id}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}

              {status === "submitted" && (
                <div className="flex items-center gap-2 pl-1 text-sm text-muted-foreground">
                  <Loader2 className="h-4 w-4 animate-spin" />
                  Thinking…
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
                mode === "library" ? "Ask about your saved papers…" : "Message Clio…"
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
          {mode === "library" && (
            <p className="mt-2 flex items-center gap-1.5 text-xs text-muted-foreground">
              <Sparkle className="h-3 w-3" />
              Answers are grounded in your library notes only.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
