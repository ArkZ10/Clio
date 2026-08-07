import { createFileRoute, useNavigate } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";
import { ChatSurface } from "@/components/clio/chat-surface";
import { fetchVaultGraph } from "@/lib/vault";
import { makeStemResolver } from "@/lib/wiki-links";

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
  const navigate = useNavigate();

  // / has no page viewer of its own, so a citation or inline [[wikilink]]
  // navigates to /vault instead of opening in place there -- same pattern as
  // library.tsx, just loaded here purely to resolve/label links rather than
  // to render anything with it directly.
  const graphQuery = useQuery({
    queryKey: ["vault", "graph"],
    queryFn: fetchVaultGraph,
  });

  const nodeByStem = useMemo(() => {
    const map = new Map<string, { title: string; category: string }>();
    for (const n of graphQuery.data?.nodes ?? []) {
      map.set(n.id, { title: n.title, category: n.category });
    }
    return map;
  }, [graphQuery.data]);

  const resolveStem = useMemo(
    () => makeStemResolver(nodeByStem.keys()),
    [nodeByStem],
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border px-6 py-4">
        <h1 className="text-sm font-medium text-muted-foreground">Chat</h1>
      </header>
      <div className="min-h-0 flex-1">
        <ChatSurface
          surface="home"
          suggestions={[
            "What decides whether a diffusion model's output is safe?",
            "What does my wiki say about remasking?",
            "Which claims are contested?",
            "What open questions am I tracking?",
          ]}
          emptySubtitle="Answers come only from your wiki. If a topic isn't in there, Clio will say so rather than guess."
          resolvePage={(stem) => nodeByStem.get(stem)}
          resolveStem={resolveStem}
          onCitationClick={(stem) => {
            void navigate({ to: "/vault", search: { page: stem } });
          }}
        />
      </div>
    </div>
  );
}
