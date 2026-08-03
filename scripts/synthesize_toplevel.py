#!/usr/bin/env python3
"""F4b: TOP-LEVEL synthesis over the per-cluster (F4a) syntheses, plus
small-cluster folding and the noise/scattered section. READ-ONLY -- writes
NOTHING (persistence is F4c). Synthesis routes to DeepSeek via the existing
routing.py table (stage='synthesis' -> 'deepseek'); no overrides.

The two-tier grounding must survive one level up: top-level claims cite
cluster_ids and may ONLY assert relations that decompose into claims already
present in the per-cluster (F4a) syntheses. This module reuses F4a's per-cluster
synthesis pipeline (synthesize_clusters.py) so the F4a call pattern/retry logic
isn't duplicated; the top-level call itself is new (Step 1 below).

Pipeline:
  Step 0  re-run the 3 per-cluster (F4a) syntheses in-memory; fold clusters with
          usable size < 3 into the scattered set; qualifying camps = size >= 3.
  Step 1  one DeepSeek call over ONLY the qualifying camps' syntheses (no raw
          paper fields).
  Step 2  verification: VALID-CLUSTER-IDS, ARITY, DECOMPOSITION view (surfaced
          for human eyeball, not auto-judged) + UNSUPPORTED-SUSPECT hard check,
          COVERAGE.
  Step 3  readout + TOP-LEVEL GROUNDING line.
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))  # Clio root, for `backend.*` imports

from backend.db import connect
from backend.config import DB_PATH
from backend.routing import resolve_stage, route_name
import llm_switch

from synthesize_clusters import (
    EXPLORE_EXPLORATION_ID,
    load_clusters,
    load_paper_meta,
    load_extraction_fields,
    build_cluster_payload,
    synthesize as synthesize_cluster,   # F4a's per-cluster call+retry, reused as-is
    trunc,
    _extract_json,
)

MIN_CAMP_SIZE = 3
TOPLEVEL_MAX_TOKENS = 8000

SYSTEM_PROMPT = """\
You are given the syntheses of N clusters (research camps), each with a
cluster_id, a theme, and grounded claims/tensions/open_problems.

Produce a FIELD-LEVEL overview as JSON:
{
  "overview": "<2-3 sentences: the shape of this field across the camps>",
  "camps": [ {"cluster_id": <id>, "one_line": "<what this camp is>"} ],
  "cross_cluster_claims": [
    {"text": "...", "cluster_ids": [<>=2 cluster ids>]}
  ],
  "cross_cluster_tensions": [ {"text": "...", "cluster_ids": [...]} ],
  "field_open_problems": [ {"text": "...", "cluster_ids": [...]} ]
}
HARD RULES:
- Every cross_cluster_* item MUST cite >=2 cluster_ids from the clusters given.
- You may ONLY cite cluster_ids provided to you.
- A cross-cluster claim may ONLY assert something that follows from the claims/
  tensions ALREADY STATED in those clusters' syntheses. Do NOT introduce facts
  not present in the provided cluster syntheses. If a relation isn't supported
  by the given cluster claims, do not make it.
Output STRICTLY the JSON, no preamble, no fences.\
"""


# ---------------------------------------------------------------- Step 0
async def run_per_cluster_synthesis(db):
    """Re-run F4a in-memory for all 3 explore clusters. Returns list of dicts:
    {cluster_id, label, raw_members, usable_members, synth}."""
    clusters = load_clusters(db)  # [(cid, label, [paper_id...])] via paper_cluster
    out = []
    for cid, label, raw_members in clusters:
        fields_by_paper = {}
        for pid in raw_members:
            fields = load_extraction_fields(db, pid)
            if fields:
                fields_by_paper[pid] = fields
        usable_members = sorted(fields_by_paper)
        synth = None
        if usable_members:
            body = build_cluster_payload(fields_by_paper)
            synth = await synthesize_cluster(body)
        out.append({
            "cluster_id": cid,
            "label": label,
            "raw_members": raw_members,
            "usable_members": usable_members,
            "synth": synth,
        })
    return out


def assemble_scattered(db, cluster_synths):
    """Noise (HDBSCAN label -1: explore papers in no paper_cluster row) +
    members of folded (usable size < MIN_CAMP_SIZE) clusters."""
    cur = db.cursor()
    cur.execute("SELECT id FROM paper WHERE source = 'explore'")
    all_explore = {r[0] for r in cur.fetchall()}
    clustered_anywhere = set()
    for c in cluster_synths:
        clustered_anywhere.update(c["raw_members"])
    noise_ids = sorted(all_explore - clustered_anywhere)

    folded = [c for c in cluster_synths if len(c["usable_members"]) < MIN_CAMP_SIZE]
    folded_member_ids = []
    for c in folded:
        folded_member_ids.extend(c["raw_members"])

    scattered_ids = sorted(set(noise_ids) | set(folded_member_ids))
    return noise_ids, folded, scattered_ids


# ---------------------------------------------------------------- Step 1
def build_camp_payload(camps):
    """The user-message body: theme + claims/tensions/open_problems per camp,
    tagged with cluster_id. NO raw paper fields sent."""
    blocks = []
    for c in camps:
        s = c["synth"]
        lines = [f"cluster_id: {c['cluster_id']}", f"theme: {s.get('theme','')}"]
        lines.append("claims:")
        for cl in s.get("claims", []) or []:
            lines.append(f"  - [{cl.get('type')}] {cl.get('text','')}")
        lines.append("tensions:")
        for t in s.get("tensions", []) or []:
            lines.append(f"  - {t.get('text','')}")
        lines.append("open_problems:")
        for o in s.get("open_problems", []) or []:
            lines.append(f"  - {o.get('text','')}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def _call_toplevel(body):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": body},
    ]
    endpoint = resolve_stage("synthesis")
    result = await llm_switch.call(
        messages, endpoint.name, thinking=False, max_tokens=TOPLEVEL_MAX_TOKENS
    )
    if not result.text.strip():
        return None
    try:
        return _extract_json(result.text)
    except (json.JSONDecodeError, ValueError):
        return None


async def synthesize_toplevel(body):
    obj = await _call_toplevel(body)
    if obj is None:
        obj = await _call_toplevel(body)  # one retry, fresh reasoning
    return obj


# ---------------------------------------------------------------- Step 2
def _iter_cross_items(top):
    for c in top.get("cross_cluster_claims", []) or []:
        yield "cross_cluster_claim", c
    for t in top.get("cross_cluster_tensions", []) or []:
        yield "cross_cluster_tension", t
    for o in top.get("field_open_problems", []) or []:
        yield "field_open_problem", o


def verify_toplevel(top, camps_by_id):
    valid_ids = set(camps_by_id)
    id_violations = []      # (section, text, bad_ids)
    arity_violations = []   # (section, text, ids)
    unsupported = []        # (section, text, cluster_id_with_zero_claims)
    cited_camps = set()

    for section, item in _iter_cross_items(top):
        ids = item.get("cluster_ids") or []
        text = item.get("text", "")

        bad = [i for i in ids if i not in valid_ids]
        if bad:
            id_violations.append((section, text, bad))

        if len(ids) < 2:
            arity_violations.append((section, text, ids))

        for i in ids:
            if i in valid_ids:
                cited_camps.add(i)
                camp = camps_by_id[i]
                s = camp["synth"] or {}
                total_items = (
                    len(s.get("claims", []) or [])
                    + len(s.get("tensions", []) or [])
                    + len(s.get("open_problems", []) or [])
                )
                if total_items == 0:
                    unsupported.append((section, text, i))

    coverage = (len(cited_camps), len(camps_by_id))
    return {
        "id_violations": id_violations,
        "arity_violations": arity_violations,
        "unsupported": unsupported,
        "coverage": coverage,
    }


def print_decomposition(item_text, cluster_ids, camps_by_id):
    """Human decomposition view: cited clusters' theme + claim texts, printed
    beneath the top-level item. Not auto-judged."""
    for cid in cluster_ids:
        camp = camps_by_id.get(cid)
        if camp is None:
            print(f"      [cluster {cid}] <NOT IN INPUT SET -- VIOLATION>")
            continue
        s = camp["synth"] or {}
        print(f"      [cluster {cid}] theme: {s.get('theme','')}")
        claims = s.get("claims", []) or []
        tensions = s.get("tensions", []) or []
        opens = s.get("open_problems", []) or []
        if not claims and not tensions and not opens:
            print(f"          (NO claims/tensions/open_problems in this cluster's synthesis)")
        for cl in claims:
            print(f"          claim [{cl.get('type')}]: {trunc(cl.get('text',''), 140)}")
        for t in tensions:
            print(f"          tension: {trunc(t.get('text',''), 140)}")
        for o in opens:
            print(f"          open_problem: {trunc(o.get('text',''), 140)}")


# ---------------------------------------------------------------- driver
async def main():
    db = connect(DB_PATH)
    print(f"synthesis stage routes to: {route_name('synthesis')} "
          f"(endpoint default_model={resolve_stage('synthesis').default_model})")
    print()

    # ===== STEP 0 =====
    print("=" * 92)
    print("STEP 0: re-run per-cluster (F4a) syntheses in-memory + folding decision")
    print("-" * 92)
    cluster_synths = await run_per_cluster_synthesis(db)
    titles_cache = {}
    for c in cluster_synths:
        titles_cache.update(load_paper_meta(db, c["raw_members"]))
        s = c["synth"]
        print(f"\nCLUSTER db.id={c['cluster_id']} ({c['label']})  "
              f"raw_size={len(c['raw_members'])}  usable_size={len(c['usable_members'])}  "
              f"raw_members={c['raw_members']}")
        if s is None:
            print("  SYNTH-FAILED (no per-cluster synthesis available)")
            continue
        print(f"  theme: {s.get('theme','')}")
        for cl in s.get("claims", []) or []:
            print(f"    claim [{cl.get('type')}] ids={cl.get('paper_ids')}  {trunc(cl.get('text',''),110)}")
        for t in s.get("tensions", []) or []:
            print(f"    tension ids={t.get('paper_ids')}  {trunc(t.get('text',''),110)}")
        for o in s.get("open_problems", []) or []:
            print(f"    open_problem ids={o.get('paper_ids')}  {trunc(o.get('text',''),110)}")

    print()
    print("-" * 92)
    print("FOLDING DECISION (usable_size < 3 -> not a top-level camp):")
    noise_ids, folded, scattered_ids = assemble_scattered(db, cluster_synths)
    for c in cluster_synths:
        if len(c["usable_members"]) < MIN_CAMP_SIZE:
            print(f"  FOLDED (size<3): cluster {c['cluster_id']} "
                  f"(usable_size={len(c['usable_members'])}) -> scattered")

    print()
    print(f"SCATTERED SET: noise(-1) count={len(noise_ids)}  "
          f"+ folded-cluster members={sum(len(c['raw_members']) for c in folded)}  "
          f"= total scattered={len(scattered_ids)}")
    all_scattered_titles = load_paper_meta(db, scattered_ids) if scattered_ids else {}
    for pid in scattered_ids:
        tag = "noise" if pid in noise_ids else "folded-cluster-member"
        print(f"    [{pid}] ({tag}) {all_scattered_titles.get(pid,'?')}")

    camps = [c for c in cluster_synths if len(c["usable_members"]) >= MIN_CAMP_SIZE]
    print()
    print(f"QUALIFYING CAMPS (usable_size >= {MIN_CAMP_SIZE}): "
          f"{[c['cluster_id'] for c in camps]}")

    camps_with_synth = [c for c in camps if c["synth"] is not None]
    if len(camps_with_synth) < len(camps):
        missing = [c["cluster_id"] for c in camps if c["synth"] is None]
        print(f"  NOTE: camps with SYNTH-FAILED excluded from top-level input: {missing}")
    camps_by_id = {c["cluster_id"]: c for c in camps_with_synth}

    # ===== STEP 1 =====
    print()
    print("=" * 92)
    print("STEP 1: top-level synthesis (one DeepSeek call over qualifying camp syntheses only)")
    print("-" * 92)
    if not camps_with_synth:
        print("  No qualifying camps with a synthesis available -- SYNTH-FAILED (top-level).")
        top = None
    else:
        body = build_camp_payload(camps_with_synth)
        top = await synthesize_toplevel(body)
        if top is None:
            print("  SYNTH-FAILED (empty/parse-fail after retry)")
        else:
            print(f"  top-level synthesis OK  "
                  f"({len(top.get('cross_cluster_claims',[]) or [])} cross-cluster claims, "
                  f"{len(top.get('cross_cluster_tensions',[]) or [])} tensions, "
                  f"{len(top.get('field_open_problems',[]) or [])} open_problems)")

    # ===== STEP 2 / 3 =====
    print()
    print("=" * 92)
    print("STEP 3: readout")
    print("=" * 92)

    if top is None:
        print("\nTOP-LEVEL SYNTHESIS FAILED -- nothing to verify.")
    else:
        print(f"\nOVERVIEW:\n  {top.get('overview','')}")

        print("\nCAMPS:")
        for c in top.get("camps", []) or []:
            print(f"  cluster_id={c.get('cluster_id')}: {c.get('one_line','')}")

        print("\nCROSS-CLUSTER CLAIMS (with decomposition view):")
        for cl in top.get("cross_cluster_claims", []) or []:
            print(f"\n  CLAIM: {cl.get('text','')}")
            print(f"    cited cluster_ids: {cl.get('cluster_ids')}")
            print_decomposition(cl.get("text", ""), cl.get("cluster_ids") or [], camps_by_id)

        tensions = top.get("cross_cluster_tensions", []) or []
        print(f"\nCROSS-CLUSTER TENSIONS ({len(tensions)}, with decomposition view):")
        for t in tensions:
            print(f"\n  TENSION: {t.get('text','')}")
            print(f"    cited cluster_ids: {t.get('cluster_ids')}")
            print_decomposition(t.get("text", ""), t.get("cluster_ids") or [], camps_by_id)

        opens = top.get("field_open_problems", []) or []
        print(f"\nFIELD OPEN PROBLEMS ({len(opens)}, with decomposition view):")
        for o in opens:
            print(f"\n  OPEN_PROBLEM: {o.get('text','')}")
            print(f"    cited cluster_ids: {o.get('cluster_ids')}")
            print_decomposition(o.get("text", ""), o.get("cluster_ids") or [], camps_by_id)

    print()
    print("-" * 92)
    print(f"SCATTERED SECTION (outliers, NOT synthesized into camps): "
          f"{len(scattered_ids)} papers")
    for pid in scattered_ids:
        print(f"    [{pid}] {all_scattered_titles.get(pid,'?')}")

    print()
    print("-" * 92)
    print("VERIFICATION SUMMARY")
    if top is None:
        print("  (no top-level output to verify)")
        print("TOP-LEVEL GROUNDING VIOLATIONS: N/A (SYNTH-FAILED)")
    else:
        v = verify_toplevel(top, camps_by_id)
        n_items = (
            len(top.get("cross_cluster_claims", []) or [])
            + len(top.get("cross_cluster_tensions", []) or [])
            + len(top.get("field_open_problems", []) or [])
        )
        n_id = len(v["id_violations"])
        n_arity = len(v["arity_violations"])
        n_unsup = len(v["unsupported"])
        cov_n, cov_d = v["coverage"]

        print(f"  #cross-cluster items: {n_items}")
        print(f"  #valid-id-violations: {n_id}")
        if v["id_violations"]:
            for section, text, bad in v["id_violations"]:
                print(f"      [{section}] bad_cluster_ids={bad}  {trunc(text)}")
        print(f"  #arity-violations: {n_arity}")
        if v["arity_violations"]:
            for section, text, ids in v["arity_violations"]:
                print(f"      [{section}] cluster_ids={ids}  {trunc(text)}")
        print(f"  #UNSUPPORTED-SUSPECT: {n_unsup}")
        if v["unsupported"]:
            for section, text, cid in v["unsupported"]:
                print(f"      [{section}] cluster {cid} contributed ZERO claims/tensions/open_problems  {trunc(text)}")
        print(f"  camp coverage: {cov_n}/{cov_d} qualifying camps cited by >=1 cross-cluster item")

        total_violations = n_id + n_arity + n_unsup
        print()
        if total_violations == 0:
            print("TOP-LEVEL GROUNDING CLEAN")
        else:
            print(f"TOP-LEVEL GROUNDING VIOLATIONS: {total_violations}")

    print("=" * 92)
    db.close()


if __name__ == "__main__":
    asyncio.run(main())
