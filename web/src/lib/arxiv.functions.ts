import { createServerFn } from "@tanstack/react-start";
import { z } from "zod";

export type ArxivPaper = {
  id: string;
  title: string;
  authors: string[];
  year: number;
  summary: string;
  pdfUrl: string;
};

export type ArxivSearchResult = {
  papers: ArxivPaper[];
  /** From the feed's <opensearch:totalResults> -- how many papers match the
   *  query in total, not just this page. Drives the page count in the UI. */
  totalResults: number;
  start: number;
  pageSize: number;
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

/** arXiv's earliest papers -- the safe floor for an open-ended "from" bound
 *  (its search_query date range needs real bounds, no wildcard), and the
 *  bottom of the year filter's range in the UI. */
export const ARXIV_FOUNDING_YEAR = 1991;

/** `all:<query>`, AND-ed with a submittedDate range when either year bound is
 *  set. Format is arXiv's own: YYYYMMDDHHMM, so a bare year becomes Jan 1
 *  00:00 through Dec 31 23:59 of that year. */
function buildSearchQuery(query: string, fromYear?: number, toYear?: number): string {
  const base = `all:${query}`;
  if (!fromYear && !toYear) return base;
  const from = Math.min(fromYear ?? ARXIV_FOUNDING_YEAR, toYear ?? Infinity);
  const to = Math.max(toYear ?? new Date().getFullYear(), fromYear ?? -Infinity);
  return `(${base}) AND submittedDate:[${from}01010000 TO ${to}12312359]`;
}

export const searchArxiv = createServerFn({ method: "POST" })
  .inputValidator((input: unknown) =>
    z
      .object({
        query: z.string().min(1),
        start: z.number().int().min(0).default(0),
        maxResults: z.number().int().min(1).max(50).default(10),
        fromYear: z.number().int().min(ARXIV_FOUNDING_YEAR).optional(),
        toYear: z.number().int().min(ARXIV_FOUNDING_YEAR).optional(),
      })
      .parse(input),
  )
  .handler(async ({ data }): Promise<ArxivSearchResult> => {
    const searchQuery = buildSearchQuery(data.query, data.fromYear, data.toYear);
    const url = `https://export.arxiv.org/api/query?search_query=${encodeURIComponent(
      searchQuery,
    )}&start=${data.start}&max_results=${data.maxResults}&sortBy=relevance`;

    const res = await fetch(url);
    if (!res.ok) throw new Error("arXiv search failed");
    const xml = await res.text();

    const totalResults = Number(pick(xml, "opensearch:totalResults")) || 0;

    const entries = xml.split("<entry>").slice(1);
    const papers = entries.map((block) => {
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
      };
    });

    return { papers, totalResults, start: data.start, pageSize: data.maxResults };
  });
