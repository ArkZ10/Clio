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
            "Explain diffusion models simply",
            "Summarise the Chinchilla scaling result",
            "Draft a related-work paragraph on RAG",
            "What should I read after LoRA?",
          ]}
          emptySubtitle="Clio is a general-purpose research assistant. Ask a question, or start from a prompt below."
        />
      </div>
    </div>
  );
}
