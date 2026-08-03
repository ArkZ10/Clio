import { createFileRoute } from "@tanstack/react-router";
import { convertToModelMessages, streamText, type UIMessage } from "ai";
import { createLovableAiGatewayProvider } from "@/lib/ai-gateway.server";
import { paperNotes } from "@/lib/clio-data";

type ChatRequestBody = { messages?: unknown; mode?: "general" | "library" };

const LIBRARY_CONTEXT = paperNotes
  .map(
    (n) =>
      `### [${n.id}] ${n.title} (${n.authors.join(", ")}, ${n.year}, arXiv:${n.arxivId})\nTags: ${n.tags.join(", ")}\nAbstract: ${n.abstract}\nUser notes: ${n.notes}`,
  )
  .join("\n\n");

export const Route = createFileRoute("/api/chat")({
  server: {
    handlers: {
      POST: async ({ request }) => {
        const body = (await request.json()) as ChatRequestBody;
        const messages = body.messages;
        if (!Array.isArray(messages)) {
          return new Response("Messages are required", { status: 400 });
        }

        const key = process.env["LOVABLE_API_KEY"];
        if (!key) return new Response("Missing LOVABLE_API_KEY", { status: 500 });

        const system =
          body.mode === "library"
            ? `You are Clio, a research assistant grounded strictly in the user's personal library of paper notes below. Answer only from these notes; if the answer is not present, say so plainly. Cite sources inline using the bracketed note id, e.g. [attention]. Be concise and use markdown.\n\n${LIBRARY_CONTEXT}`
            : "You are Clio, a calm, precise research assistant. Answer clearly in markdown, prefer structure over prose padding, and flag uncertainty explicitly.";

        try {
          const gateway = createLovableAiGatewayProvider(key);
          const result = streamText({
            model: gateway("google/gemini-3.6-flash"),
            system,
            messages: await convertToModelMessages(messages as UIMessage[]),
          });
          return result.toUIMessageStreamResponse({
            originalMessages: messages as UIMessage[],
          });
        } catch {
          return new Response("Failed to reach the AI gateway", { status: 502 });
        }
      },
    },
  },
});
