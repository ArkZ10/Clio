import { createFileRoute } from "@tanstack/react-router";
import { ChatSurface } from "@/components/clio/chat-surface";

export const Route = createFileRoute("/")({
  head: () => ({
    meta: [
      { title: "Clio — Chat with your research assistant" },
      {
        name: "description",
        content:
          "Clio is a calm, dark-themed research assistant. Ask questions, keep paper notes, and discover new arXiv work.",
      },
      { property: "og:title", content: "Clio — Chat with your research assistant" },
      {
        property: "og:description",
        content: "Ask anything, keep paper notes, and discover new arXiv research with Clio.",
      },
    ],
  }),
  component: ChatPage,
});

function ChatPage() {
  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">Chat</h1>
      </header>
      <div className="min-h-0 flex-1">
        <ChatSurface
          suggestions={[
            "What decides whether a diffusion model's output is safe?",
            "What does my wiki say about remasking?",
            "Which claims are contested?",
            "What open questions am I tracking?",
          ]}
          emptySubtitle="Answers come only from your wiki. If a topic isn't in there, Clio will say so rather than guess."
        />
      </div>
    </div>
  );
}
