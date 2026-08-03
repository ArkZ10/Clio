# Clio Research Hub

Build a dark-themed research assistant app called Clio. It has three main sections

accessible from a persistent left sidebar.

COLOR PALETTE (use exactly these):

- Background / base: #0B0B0B (near-black)

- Primary accent / active states / buttons: #7A29A3 (vivid purple)

- Secondary accent / hover / borders: #591E82 (deep purple)

- Surface / cards / panels: #1F0D31 (very dark purple)

- Elevated surface / sidebar / input fields: #3D155D (dark violet)

- Text: white/near-white primary, muted grey-lavender for secondary text

Dark mode only. Generous whitespace, rounded corners (8-12px), subtle borders using

#591E82 at low opacity. Modern, calm, research-tool aesthetic — not flashy.

LAYOUT:

Left sidebar (fixed, ~240px, background #3D155D): Clio logo/wordmark at top, then

three nav items with icons — "Chat", "Library", "Explore". Active item highlighted

with #7A29A3. User settings at the bottom.

--- SECTION 1: CHAT ---

A general-purpose LLM chat interface. Centered conversation column (max ~760px).

Message bubbles: user messages right-aligned with #7A29A3 background; assistant

messages left-aligned on #1F0D31 surface. Input bar fixed at bottom with a rounded

#3D155D field, send button in #7A29A3. Empty state: "Ask me anything" with 3-4

suggested prompt chips.

--- SECTION 2: LIBRARY ---

The user's read papers, stored as markdown notes. Two-pane layout:

- Left pane (~40%): a searchable list of paper notes. Each row shows title, authors,

  year, and 2-3 small tag pills in #591E82.

- Right pane (~60%): the selected note rendered as clean markdown — title, metadata,

  abstract, and the user's own annotations. A "Linked papers" section at the bottom

  showing related notes as clickable chips.

- Top-right of this section: a toggle to switch between "Notes" view and "Graph"

  view.

- GRAPH VIEW: a force-directed graph of the paper notes — circular nodes connected

  by thin lines. Nodes colored in #7A29A3, with clustered groups in varying shades

  (#591E82, #3D155D). Hovering a node shows a tooltip with the paper title. Dark

  #0B0B0B canvas.

- Also in Library: a chat panel that can be opened (slide-over from the right, or a

  bottom bar) labeled "Chat with your library" — same chat UI as Section 1, but

  with a small badge indicating it's grounded in the user's notes. Include citation

  chips beneath assistant answers linking to the source notes.

--- SECTION 3: EXPLORE ---

Discover new papers from arXiv. Layout:

- A prominent centered search bar at the top: "What do you want to explore?" with a

  #7A29A3 search button.

- Below it, results as a ranked list of up to 10 paper cards. Each card (#1F0D31

  surface, rounded, subtle #591E82 border) shows: rank number in a #7A29A3 circle,

  paper title, authors, year, arXiv ID, a truncated abstract (3 lines), and a

  relevance score badge. Card actions on hover: "Save to Library" and "Open PDF".

- Loading state: skeleton cards with a subtle purple shimmer.

- Empty state: illustration-free, just centered muted text with example queries as

  clickable chips.

Make it responsive. Prioritize clarity and readability over decoration.

This project was built with [Lovable](https://lovable.dev).

## Build with Lovable

Continue developing this project in the [Lovable editor](https://lovable.dev/projects/ede826b1-d75d-4ccb-aacf-c07bac9cefdf).

- **Ship faster**: describe what you want to build and Lovable handles the code.
- **Stay in sync**: every change made in Lovable is committed straight to this repository.
- **Full ownership**: this code is yours. Push to `main` on GitHub and your changes sync back into Lovable, ready for your next prompt.

## Development

Prefer working locally? You need Node.js and npm — [install with nvm](https://github.com/nvm-sh/nvm#installing-and-updating).

```sh
git clone <this-repository-url>
cd <repository-name>
npm i
npm run dev
```
