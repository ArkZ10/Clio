import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

export type ArxivPaper = {
  id: string;
  title: string;
  authors: string[];
  year: number;
  summary: string;
  pdfUrl: string;
  score: number;
};

const decode = (s: string) =>
  s
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/&amp;/g, "&")
    .replace(/\s+/g, " ")
    .trim();

const pick = (block: string, tag: string) => {
  const m = block.match(new RegExp(`<${tag}[^>]*>([\\s\\S]*?)</${tag}>`));
  return m?.[1] ? decode(m[1]) : "";
};

export const searchArxiv = createServerFn({ method: "POST" })
  .inputValidator((input: unknown) => z.object({ query: z.string().min(1) }).parse(input))
  .handler(async ({ data }): Promise<ArxivPaper[]> => {
    const url = `https://export.arxiv.org/api/query?search_query=all:${encodeURIComponent(
      data.query,
    )}&start=0&max_results=10&sortBy=relevance`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("arXiv search failed");
    const xml = await res.text();

    const entries = xml.split("<entry>").slice(1);
    return entries.map((block, i) => {
      const rawId = pick(block, "id");
      const idMatch = rawId.match(/abs\/([^v]+)(v\d+)?/);
      const published = pick(block, "published");
      const authors = [...block.matchAll(/<name>([\s\S]*?)<\/name>/g)].map((m) =>
        decode(m[1] ?? ""),
      );
      return {
        id: idMatch?.[1] ?? rawId,
        title: pick(block, "title"),
        authors,
        year: Number(published.slice(0, 4)) || new Date().getFullYear(),
        summary: pick(block, "summary"),
        pdfUrl: rawId.replace("/abs/", "/pdf/"),
        score: Math.max(0.4, Number((0.98 - i * 0.045).toFixed(2))),
      };
    });
  });
