#!/usr/bin/env python3
"""Per-cluster synthesis, read-only, with citation verification. Proves
two-tier grounding on relational claims before any top-level pass or
persistence. Writes nothing to the DB. Routes to deepseek via routing.py.

Pipeline per cluster:
  1. assemble inputs (member extraction field values; dropped/NULL skipped)
  2. one synthesis call (retry once on empty/parse-fail)
  3. citation verification: valid ids, type/arity, coverage
  4. readout + grounding line
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

import dotenv

dotenv.load_dotenv(ROOT / ".env")

import llm_switch
from backend.config import DB_PATH
from backend.db import connect
from backend.routing import resolve_stage, route_name
from spike_f3a_extract import _extract_json

EXPLORE_EXPLORATION_ID = 1
FIELDS = ["problem", "method", "result", "contribution"]
SYNTH_MAX_TOKENS = 8000

SYSTEM_PROMPT = """\
You are given the extracted summaries (problem, method, result, contribution) of
N papers that were grouped into one cluster by embedding similarity. Each paper
is identified by its paper_id.

Produce a synthesis of THIS cluster as JSON:
{
  "theme": "<1 sentence: what unifies these papers>",
  "claims": [
    {
      "text": "<a claim about this cluster>",
      "type": "single" | "relational",
      "paper_ids": [<ids this claim rests on>]
    }
  ],
  "tensions": [ {"text": "...", "paper_ids": [...]} ],
  "open_problems": [ {"text": "...", "paper_ids": [...]} ]
}

HARD RULES:
- Every claim, tension, and open_problem MUST list the paper_ids it is based on.
- "single" = a fact about ONE paper -> exactly one paper_id.
- "relational" = about multiple papers -> two or more paper_ids.
- You may ONLY cite paper_ids from the papers given to you in THIS cluster.
- A claim may only assert what the given extracted fields support. Do NOT
  introduce facts not present in the provided summaries. If you cannot ground a
  claim in the given fields, do not make it.
Output STRICTLY the JSON, no preamble, no fences.\
"""


# ---------------------------------------------------------------- Step 0
def load_clusters(db):
    """Return [(cluster_id, label, [paper_id...])] for exploration_id=1."""
    cur = db.cursor()
    cur.execute(
        "SELECT id, label FROM cluster WHERE exploration_id = ? ORDER BY id",
        (EXPLORE_EXPLORATION_ID,),
    )
    clusters = []
    for cid, label in cur.fetchall():
        cur.execute(
            "SELECT paper_id FROM paper_cluster WHERE cluster_id = ? ORDER BY paper_id",
            (cid,),
        )
        members = [r[0] for r in cur.fetchall()]
        clusters.append((cid, label, members))
    return clusters


def load_paper_meta(db, paper_ids):
    cur = db.cursor()
    qmarks = ",".join("?" for _ in paper_ids)
    cur.execute(f"SELECT id, title FROM paper WHERE id IN ({qmarks})", paper_ids)
    return {r[0]: r[1] for r in cur.fetchall()}


def load_extraction_fields(db, paper_id):
    """Return {field: value} for non-NULL extracted values, or None if no row."""
    cur = db.cursor()
    cols = ", ".join(f"{f}_value" for f in FIELDS)
    cur.execute(
        f"SELECT {cols} FROM extractions WHERE paper_id = ?", (paper_id,)
    )
    row = cur.fetchone()
    if row is None:
        return None
    return {f: v for f, v in zip(FIELDS, row) if v is not None and str(v).strip()}


def build_cluster_payload(fields_by_paper):
    """The user-message body sent to DeepSeek: one block per paper."""
    blocks = []
    for pid in sorted(fields_by_paper):
        fields = fields_by_paper[pid]
        lines = [f"paper_id: {pid}"]
        for f in FIELDS:
            if f in fields:
                lines.append(f"  {f}: {fields[f]}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


# ---------------------------------------------------------------- Step 1
async def _call_synthesis(user_body):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_body},
    ]
    endpoint = resolve_stage("synthesis")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=SYNTH_MAX_TOKENS
    )
    if not result.text.strip():
        return None
    try:
        return _extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        return None


async def synthesize(user_body):
    obj = await _call_synthesis(user_body)
    if obj is None:
        obj = await _call_synthesis(user_body)  # one retry, fresh reasoning
    return obj


# ---------------------------------------------------------------- Step 2
def _iter_citing_items(synth):
    """Yield (section, item) for every claim/tension/open_problem."""
    for c in synth.get("claims", []) or []:
        yield "claim", c
    for t in synth.get("tensions", []) or []:
        yield "tension", t
    for o in synth.get("open_problems", []) or []:
        yield "open_problem", o


def verify_citations(synth, member_ids):
    member_set = set(member_ids)
    id_violations = []     # (section, text, bad_ids)
    arity_violations = []  # (text, type, ids)
    cited = set()

    for section, item in _iter_citing_items(synth):
        ids = item.get("paper_ids") or []
        text = item.get("text", "")
        bad = [i for i in ids if i not in member_set]
        if bad:
            id_violations.append((section, text, bad))
        for i in ids:
            if i in member_set:
                cited.add(i)

    # TYPE-ARITY applies to claims (they carry a "type").
    for c in synth.get("claims", []) or []:
        ids = c.get("paper_ids") or []
        ctype = c.get("type")
        if ctype == "single" and len(ids) != 1:
            arity_violations.append((c.get("text", ""), ctype, ids))
        elif ctype == "relational" and len(ids) < 2:
            arity_violations.append((c.get("text", ""), ctype, ids))

    coverage = (len(cited & member_set), len(member_set))
    return {
        "id_violations": id_violations,
        "arity_violations": arity_violations,
        "coverage": coverage,
        "cited": sorted(cited & member_set),
    }


# ---------------------------------------------------------------- driver
def trunc(s, n=120):
    s = str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


async def main():
    db = connect(DB_PATH)
    print(f"synthesis stage routes to: {route_name('synthesis')} "
          f"(endpoint default_model={resolve_stage('synthesis').default_model})")
    print()

    clusters = load_clusters(db)

    # ===== STEP 0 =====
    print("=" * 92)
    print("STEP 0: assemble per-cluster inputs (READ-ONLY)")
    print("-" * 92)
    prepared = []  # (cid, label, fields_by_paper, titles, excluded)
    for cid, label, members in clusters:
        titles = load_paper_meta(db, members)
        fields_by_paper = {}
        excluded = []
        for pid in members:
            fields = load_extraction_fields(db, pid)
            if fields is None or not fields:
                excluded.append(pid)
                continue
            fields_by_paper[pid] = fields
        prepared.append((cid, label, fields_by_paper, titles, excluded))

        print(f"\nCLUSTER db.id={cid} ({label})  size={len(members)}  "
              f"member_ids={members}")
        if excluded:
            print(f"  EXCLUDED (no extraction row / no usable fields): {excluded}")
        for pid in sorted(fields_by_paper):
            print(f"  [{pid}] {trunc(titles.get(pid,'?'), 70)}")
            for f in FIELDS:
                if f in fields_by_paper[pid]:
                    print(f"        {f:12}: {trunc(fields_by_paper[pid][f])}")

    # ===== STEP 1 =====
    print()
    print("=" * 92)
    print("STEP 1: per-cluster synthesis (one DeepSeek call each, retry once)")
    print("-" * 92)
    results = []  # (cid, label, member_ids_used, synth_or_None)
    for cid, label, fields_by_paper, titles, excluded in prepared:
        member_ids = sorted(fields_by_paper)
        if not member_ids:
            print(f"  cluster {cid}: no usable members -> skipped")
            results.append((cid, label, member_ids, None))
            continue
        body = build_cluster_payload(fields_by_paper)
        synth = await synthesize(body)
        if synth is None:
            print(f"  cluster {cid}: SYNTH-FAILED (empty/parse-fail after retry)")
        else:
            nclaims = len(synth.get("claims", []) or [])
            print(f"  cluster {cid}: synthesis OK  ({nclaims} claims, "
                  f"{len(member_ids)} papers in)")
        results.append((cid, label, member_ids, synth))

    # ===== STEP 2 + 3 =====
    print()
    print("=" * 92)
    print("STEP 3: full synthesis + verification per cluster")
    print("=" * 92)
    table_rows = []
    total_violations = 0
    violation_clusters = []

    for cid, label, member_ids, synth in results:
        print(f"\n{'#'*92}\nCLUSTER db.id={cid} ({label})  members_used={member_ids}")
        print("#" * 92)
        if synth is None:
            print("  SYNTH-FAILED -- no JSON to verify.")
            table_rows.append((cid, "FAILED", "-", "-", "-"))
            violation_clusters.append((cid, "SYNTH-FAILED"))
            continue

        print(f"  THEME: {synth.get('theme','')}")
        print("  CLAIMS:")
        for c in synth.get("claims", []) or []:
            print(f"    - [{c.get('type')}] ids={c.get('paper_ids')}  {c.get('text','')}")
        tensions = synth.get("tensions", []) or []
        print(f"  TENSIONS ({len(tensions)}):")
        for t in tensions:
            print(f"    - ids={t.get('paper_ids')}  {t.get('text','')}")
        opens = synth.get("open_problems", []) or []
        print(f"  OPEN_PROBLEMS ({len(opens)}):")
        for o in opens:
            print(f"    - ids={o.get('paper_ids')}  {o.get('text','')}")

        v = verify_citations(synth, member_ids)
        nclaims = len(synth.get("claims", []) or [])
        nid = len(v["id_violations"])
        narity = len(v["arity_violations"])
        cov_n, cov_d = v["coverage"]

        print("  --- verification ---")
        if v["id_violations"]:
            print(f"    ID-VIOLATIONS ({nid}):")
            for section, text, bad in v["id_violations"]:
                print(f"      [{section}] bad_ids={bad}  {trunc(text)}")
        else:
            print("    ID-VIOLATIONS: 0")
        if v["arity_violations"]:
            print(f"    ARITY-VIOLATIONS ({narity}):")
            for text, ctype, ids in v["arity_violations"]:
                print(f"      type={ctype} ids={ids}  {trunc(text)}")
        else:
            print("    ARITY-VIOLATIONS: 0")
        print(f"    COVERAGE: {cov_n}/{cov_d} members cited  "
              f"(uncited: {sorted(set(member_ids) - set(v['cited']))})")

        cl_viol = nid + narity
        total_violations += cl_viol
        if cl_viol:
            violation_clusters.append((cid, f"{nid} id + {narity} arity"))
        table_rows.append((cid, nclaims, nid, narity, f"{cov_n}/{cov_d}"))

    # ===== summary table + grounding line =====
    print()
    print("=" * 92)
    print("VERIFICATION SUMMARY")
    print("-" * 92)
    print(f"  {'cluster':>8} | {'#claims':>7} | {'#ID-viol':>8} | {'#arity-viol':>11} | {'coverage':>8}")
    for cid, nclaims, nid, narity, cov in table_rows:
        print(f"  {cid:>8} | {str(nclaims):>7} | {str(nid):>8} | {str(narity):>11} | {cov:>8}")
    print("-" * 92)
    if total_violations == 0 and not any(s is None for *_, s in results):
        print("GROUNDING CLEAN")
    elif total_violations == 0:
        print("GROUNDING CLEAN (citations) -- but note SYNTH-FAILED cluster(s): "
              f"{[c for c, r in violation_clusters if r == 'SYNTH-FAILED']}")
    else:
        print(f"GROUNDING VIOLATIONS: {total_violations}  -> "
              + "; ".join(f"cluster {c}: {r}" for c, r in violation_clusters))
    print("=" * 92)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
