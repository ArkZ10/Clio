#!/usr/bin/env python3
"""Fetches PDFs for explore papers from arXiv, persists them, measures text
length. arxiv 4.0.0 dropped Result.download_pdf, so this uses arxiv's
Client/Search only to resolve each pdf_url, then HTTP-GETs it with httpx. No
extraction, no LLM, no chunking -- just fetch, persist pdf_path, measure length.
"""
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import arxiv
import httpx
import pymupdf4llm

from backend.config import DB_PATH, PDF_DIR
from backend.db import connect
from backend.explore.retrieve import _strip_version  # reuse version-stripping

EXPLORE_PDF_DIR = PDF_DIR / "explore"
INPUT_GATE = 120_000
DOWNLOAD_DELAY_S = 3  # arXiv politeness: ~1 request / 3s
DOWNLOAD_TIMEOUT_S = 90


def step0(cur):
    print("=" * 80)
    print("STEP 0: inspect")
    print("-" * 80)
    cur.execute("SELECT COUNT(*) FROM paper WHERE source='explore'")
    total = cur.fetchone()[0]
    cur.execute(
        "SELECT COUNT(*) FROM paper WHERE source='explore' "
        "AND arxiv_id IS NOT NULL AND arxiv_id != ''"
    )
    fetchable = cur.fetchone()[0]
    cur.execute(
        "SELECT id, title FROM paper WHERE source='explore' "
        "AND (arxiv_id IS NULL OR arxiv_id='')"
    )
    null_rows = cur.fetchall()
    print(f"  explore papers: {total}")
    print(f"  fetchable (usable arxiv_id): {fetchable}")
    print(f"  null arxiv_id (parked, NOT fetchable): {len(null_rows)}")
    for pid, title in null_rows:
        print(f"      parked id={pid}: {title[:60]}")
    EXPLORE_PDF_DIR.mkdir(parents=True, exist_ok=True)
    print(f"  library PDFs dir : {PDF_DIR}")
    print(f"  explore target   : {EXPLORE_PDF_DIR}  (created)")
    print(f"  mapping          : explore paper.id -> {EXPLORE_PDF_DIR}/<arxiv_id>.pdf -> pdf_path column")
    print(f"  download method  : arxiv Client/Search -> result.pdf_url, then httpx GET")
    print()


def resolve_pdf_urls(arxiv_ids: list[str]) -> dict[str, str]:
    """One id_list search (reusing arxiv's Client) -> {stripped_id: pdf_url}."""
    client = arxiv.Client(delay_seconds=3, num_retries=3)
    search = arxiv.Search(id_list=arxiv_ids, max_results=len(arxiv_ids))
    urls = {}
    for r in client.results(search):
        urls[_strip_version(r.get_short_id())] = r.pdf_url
    return urls


def download_pdf(url: str, dest: Path) -> tuple[bool, str]:
    """GET a PDF; only persist if the body is a real PDF (%PDF magic)."""
    try:
        with httpx.Client(follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_S) as c:
            resp = c.get(url)
        if resp.status_code != 200:
            return False, f"HTTP {resp.status_code}"
        if not resp.content.startswith(b"%PDF"):
            return False, "response is not a PDF (likely HTML placeholder/withdrawn)"
        dest.write_bytes(resp.content)
        return True, "ok"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def step1_fetch(db, cur):
    print("=" * 80)
    print("STEP 1: fetch (rate-limited, idempotent, fail-soft)")
    print("-" * 80)
    cur.execute(
        "SELECT id, arxiv_id, pdf_path FROM paper "
        "WHERE source='explore' AND arxiv_id IS NOT NULL AND arxiv_id != '' ORDER BY id"
    )
    rows = cur.fetchall()

    # Resolve pdf_urls only for the ones we might actually need to download.
    need_urls = [aid for _id, aid, pp in rows
                 if not (pp and Path(pp).exists())]
    url_map = resolve_pdf_urls(need_urls) if need_urls else {}

    fetched = skipped = failed = 0
    first_download = True
    for pid, arxiv_id, pdf_path in rows:
        if pdf_path and Path(pdf_path).exists():
            print(f"  skip (cached): id={pid}  {arxiv_id}")
            skipped += 1
            continue

        url = url_map.get(arxiv_id)
        if not url:
            print(f"  FETCH FAIL: id={pid} {arxiv_id} no pdf_url from arxiv (withdrawn/not found)")
            failed += 1
            continue

        if not first_download:
            time.sleep(DOWNLOAD_DELAY_S)  # politeness between downloads
        first_download = False

        dest = EXPLORE_PDF_DIR / f"{arxiv_id}.pdf"
        ok, reason = download_pdf(url, dest)
        if ok:
            abs_path = str(dest.resolve())
            cur.execute("UPDATE paper SET pdf_path = ? WHERE id = ?", (abs_path, pid))
            db.commit()
            print(f"  id={pid:<3} {arxiv_id:<14} -> fetched")
            fetched += 1
        else:
            print(f"  FETCH FAIL: id={pid} {arxiv_id} {reason}")
            failed += 1

    print()
    print(f"  totals: fetched={fetched}  skipped={skipped}  failed={failed}")
    print()


def step2_measure(cur):
    print("=" * 80)
    print("STEP 2: measure markdown length (no LLM, just len)")
    print("-" * 80)
    cur.execute(
        "SELECT id, pdf_path FROM paper "
        "WHERE source='explore' AND pdf_path IS NOT NULL ORDER BY id"
    )
    measured = []
    for pid, pdf_path in cur.fetchall():
        if not Path(pdf_path).exists():
            continue
        md = pymupdf4llm.to_markdown(pdf_path)
        n = len(md)
        flag = "OVER" if n > INPUT_GATE else "under"
        print(f"  id={pid:<3} chars={n:>7}  [{flag} {INPUT_GATE}]")
        measured.append((pid, n))
    print()
    return measured


def step3_distribution(measured):
    print("=" * 80)
    print("STEP 3: distribution + chunking-priority readout")
    print("-" * 80)
    if not measured:
        print("  no explore papers measured")
        print("=" * 80)
        return
    counts = [n for _id, n in measured]
    over = [(pid, n) for pid, n in measured if n > INPUT_GATE]
    print(f"  measured: {len(measured)}")
    print(f"  min={min(counts)}  median={int(statistics.median(counts))}  max={max(counts)}")
    print(f"  over-length (> {INPUT_GATE}): {len(over)}")
    rate = 100 * len(over) / len(measured)
    print(f"  over-length rate: {rate:.1f}% of measured explore papers")
    if over:
        print("  over-length papers:")
        for pid, n in over:
            print(f"      id={pid}  chars={n}")
    print()
    print("  library tail for comparison: 2/18 over-length (126k, 137k chars)")
    print("=" * 80)


def main():
    db = connect(DB_PATH)
    cur = db.cursor()
    step0(cur)
    step1_fetch(db, cur)
    measured = step2_measure(cur)
    step3_distribution(measured)
    db.close()


if __name__ == "__main__":
    main()
