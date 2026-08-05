#!/usr/bin/env python3
"""Persists the explore synthesis (per-cluster + top-level + the scattered
list), keyed to exploration_id=1, with the cluster->paper_id mapping so
cluster-cited top-level claims resolve to papers.

Regenerates both tiers in-memory via their existing generators
(synthesize_clusters.py / synthesize_toplevel.py) -- reused, not modified. If
grounding isn't clean at either tier, this stops and persists nothing.

Idempotent per exploration_id: re-running replaces the prior run.
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from backend.config import DB_PATH
from backend.db import connect
from backend.routing import resolve_stage, route_name

from synthesize_clusters import (
    EXPLORE_EXPLORATION_ID,
    verify_citations,
)
from synthesize_toplevel import (
    MIN_CAMP_SIZE,
    run_per_cluster_synthesis,
    assemble_scattered,
    build_camp_payload,
    synthesize_toplevel,
    verify_toplevel,
)

MODEL_TAG = "deepseek"


# ---------------------------------------------------------------- STEP 0
async def regenerate_and_verify(db):
    """Returns (cluster_synths, camps, top, noise_ids, folded, scattered_ids) or
    raises RuntimeError with a diagnostic message if grounding isn't CLEAN."""
    print("=" * 92)
    print("STEP 0: regenerate + re-verify (in-memory, no writes yet)")
    print("-" * 92)
    print(f"synthesis stage routes to: {route_name('synthesis')} "
          f"(endpoint default_model={resolve_stage('synthesis').default_model})")
    print()

    # ---- (a) F4a: per-cluster synthesis for 20 (folded), 21, 22 ----
    cluster_synths = await run_per_cluster_synthesis(db)
    f4a_violations = 0
    for c in cluster_synths:
        cid, s, usable = c["cluster_id"], c["synth"], c["usable_members"]
        if s is None:
            f4a_violations += 1
            print(f"  cluster {cid}: SYNTH-FAILED")
            continue
        v = verify_citations(s, usable)
        n_viol = len(v["id_violations"]) + len(v["arity_violations"])
        f4a_violations += n_viol
        n_claims = len(s.get("claims", []) or [])
        print(f"  cluster {cid}: {n_claims} claims, "
              f"id_viol={len(v['id_violations'])} arity_viol={len(v['arity_violations'])} "
              f"coverage={v['coverage'][0]}/{v['coverage'][1]}")
        if v["id_violations"]:
            # DEBUG (diagnostic only -- does not change verification logic):
            # dump the raw bad ids + their python types to distinguish a real
            # hallucination from a JSON string-vs-int citation mismatch.
            for section, text, bad in v["id_violations"][:5]:
                print(f"      DEBUG bad_ids={bad} types={[type(b).__name__ for b in bad]}  "
                      f"member_ids sample types={[type(m).__name__ for m in list(usable)[:2]]}")

    if f4a_violations:
        raise RuntimeError(
            f"F4a GROUNDING NOT CLEAN: {f4a_violations} violation(s)/failure(s) "
            f"across per-cluster syntheses. STOPPING -- nothing persisted."
        )
    print("  F4a grounding: CLEAN")

    # ---- (b) F4b: top-level over qualifying camps ----
    camps = [c for c in cluster_synths if len(c["usable_members"]) >= MIN_CAMP_SIZE]
    camps_by_id = {c["cluster_id"]: c for c in camps}
    body = build_camp_payload(camps)
    top = await synthesize_toplevel(body)
    if top is None:
        raise RuntimeError("F4b SYNTH-FAILED (top-level). STOPPING -- nothing persisted.")

    v_top = verify_toplevel(top, camps_by_id)
    n_top_viol = (
        len(v_top["id_violations"]) + len(v_top["arity_violations"]) + len(v_top["unsupported"])
    )
    n_items = (
        len(top.get("cross_cluster_claims", []) or [])
        + len(top.get("cross_cluster_tensions", []) or [])
        + len(top.get("field_open_problems", []) or [])
    )
    print(f"  top-level: {n_items} cross-cluster items, "
          f"id_viol={len(v_top['id_violations'])} arity_viol={len(v_top['arity_violations'])} "
          f"unsupported={len(v_top['unsupported'])} "
          f"coverage={v_top['coverage'][0]}/{v_top['coverage'][1]}")

    if n_top_viol:
        detail_lines = []
        for section, text, bad in v_top["id_violations"]:
            detail_lines.append(f"    ID-VIOLATION [{section}] bad_cluster_ids={bad}  {text}")
        for section, text, ids in v_top["arity_violations"]:
            detail_lines.append(f"    ARITY-VIOLATION [{section}] cluster_ids={ids}  {text}")
        for section, text, cid in v_top["unsupported"]:
            detail_lines.append(f"    UNSUPPORTED-SUSPECT [{section}] cluster {cid} had zero claims  {text}")
        raise RuntimeError(
            f"F4b GROUNDING NOT CLEAN: {n_top_viol} violation(s). "
            f"STOPPING -- nothing persisted.\n" + "\n".join(detail_lines)
        )
    print("  F4b grounding: CLEAN")

    # ---- (c) scattered set ----
    noise_ids, folded, scattered_ids = assemble_scattered(db, cluster_synths)

    n_camps = len(camps)
    n_cluster_claims = sum(len(c["synth"].get("claims", []) or []) for c in camps)
    print()
    print(f"regenerated: {n_camps} camps, {n_cluster_claims} per-cluster claims, "
          f"{n_items} top-level items, {len(scattered_ids)} scattered "
          f"— grounding CLEAN")

    return cluster_synths, camps, top, noise_ids, folded, scattered_ids


# ---------------------------------------------------------------- STEP 2
def replace_existing_run(db, exploration_id):
    cur = db.cursor()
    cur.execute(
        "SELECT id FROM synthesis_run WHERE exploration_id = ?", (exploration_id,)
    )
    row = cur.fetchone()
    if row is None:
        print("first run (no existing synthesis_run for this exploration_id)")
        return None
    old_run_id = row[0]
    for tbl in (
        "synthesis_cluster",
        "synthesis_toplevel_item",
        "synthesis_cluster_member",
        "synthesis_scattered",
    ):
        cur.execute(f"DELETE FROM {tbl} WHERE run_id = ?", (old_run_id,))
    cur.execute("DELETE FROM synthesis_run WHERE id = ?", (old_run_id,))
    db.commit()
    print(f"replaced existing run (old run_id={old_run_id})")
    return old_run_id


def persist(db, camps, top, noise_ids, folded, scattered_ids):
    cur = db.cursor()
    now = datetime.now(timezone.utc).isoformat()

    cur.execute(
        """
        INSERT INTO synthesis_run
            (exploration_id, created_at, n_camps, n_scattered, overview, model)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (EXPLORE_EXPLORATION_ID, now, len(camps), len(scattered_ids),
         top.get("overview", ""), MODEL_TAG),
    )
    run_id = cur.lastrowid

    n_cluster_rows = 0
    n_member_rows = 0
    for c in camps:
        cid, s = c["cluster_id"], c["synth"]
        claims_blob = json.dumps({
            "claims": s.get("claims", []) or [],
            "tensions": s.get("tensions", []) or [],
            "open_problems": s.get("open_problems", []) or [],
        })
        cur.execute(
            """
            INSERT INTO synthesis_cluster (run_id, cluster_id, theme, claims_json)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, cid, s.get("theme", ""), claims_blob),
        )
        n_cluster_rows += 1
        for pid in c["raw_members"]:
            cur.execute(
                """
                INSERT INTO synthesis_cluster_member (run_id, cluster_id, paper_id)
                VALUES (?, ?, ?)
                """,
                (run_id, cid, pid),
            )
            n_member_rows += 1

    n_item_rows = 0
    for cl in top.get("cross_cluster_claims", []) or []:
        cur.execute(
            "INSERT INTO synthesis_toplevel_item (run_id, kind, text, cluster_ids_json) "
            "VALUES (?, 'claim', ?, ?)",
            (run_id, cl.get("text", ""), json.dumps(cl.get("cluster_ids") or [])),
        )
        n_item_rows += 1
    for t in top.get("cross_cluster_tensions", []) or []:
        cur.execute(
            "INSERT INTO synthesis_toplevel_item (run_id, kind, text, cluster_ids_json) "
            "VALUES (?, 'tension', ?, ?)",
            (run_id, t.get("text", ""), json.dumps(t.get("cluster_ids") or [])),
        )
        n_item_rows += 1
    for o in top.get("field_open_problems", []) or []:
        cur.execute(
            "INSERT INTO synthesis_toplevel_item (run_id, kind, text, cluster_ids_json) "
            "VALUES (?, 'open_problem', ?, ?)",
            (run_id, o.get("text", ""), json.dumps(o.get("cluster_ids") or [])),
        )
        n_item_rows += 1

    n_scattered_rows = 0
    folded_pids = set()
    for c in folded:
        folded_pids.update(c["raw_members"])
    noise_set = set(noise_ids)
    for pid in scattered_ids:
        reason = "noise" if pid in noise_set else "folded_small_cluster"
        cur.execute(
            "INSERT INTO synthesis_scattered (run_id, paper_id, reason) VALUES (?, ?, ?)",
            (run_id, pid, reason),
        )
        n_scattered_rows += 1

    db.commit()
    return run_id, {
        "synthesis_run": 1,
        "synthesis_cluster": n_cluster_rows,
        "synthesis_toplevel_item": n_item_rows,
        "synthesis_cluster_member": n_member_rows,
        "synthesis_scattered": n_scattered_rows,
    }


# ---------------------------------------------------------------- STEP 3
def read_back(db, run_id):
    cur = db.cursor()
    print("=" * 92)
    print("STEP 3: read-back proof")
    print("-" * 92)

    row = cur.execute(
        "SELECT exploration_id, created_at, n_camps, n_scattered, overview, model "
        "FROM synthesis_run WHERE id = ?",
        (run_id,),
    ).fetchone()
    print(f"RUN id={run_id}  exploration_id={row[0]}  created_at={row[1]}  "
          f"n_camps={row[2]}  n_scattered={row[3]}  model={row[5]}")
    print(f"  overview: {row[4]}")

    print()
    print("CAMPS:")
    for cid, theme, claims_json in cur.execute(
        "SELECT cluster_id, theme, claims_json FROM synthesis_cluster "
        "WHERE run_id = ? ORDER BY cluster_id",
        (run_id,),
    ).fetchall():
        blob = json.loads(claims_json)
        print(f"  cluster_id={cid}  claims={len(blob['claims'])} "
              f"tensions={len(blob['tensions'])} open_problems={len(blob['open_problems'])}")
        print(f"    theme: {theme}")

    print()
    print("TOP-LEVEL ITEMS:")
    items = cur.execute(
        "SELECT id, kind, text, cluster_ids_json FROM synthesis_toplevel_item "
        "WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    for iid, kind, text, cids_json in items:
        print(f"  [{kind}] cluster_ids={json.loads(cids_json)}  {text}")

    print()
    print("RESOLUTION CHECK (cluster_ids -> papers, via synthesis_cluster_member):")
    if items:
        iid, kind, text, cids_json = items[0]
        cited = json.loads(cids_json)
        print(f"  top-level item: [{kind}] {text}")
        print(f"  cited cluster_ids: {cited}")
        all_papers = []
        for cid in cited:
            papers = [
                r[0] for r in cur.execute(
                    "SELECT paper_id FROM synthesis_cluster_member "
                    "WHERE run_id = ? AND cluster_id = ? ORDER BY paper_id",
                    (run_id, cid),
                ).fetchall()
            ]
            all_papers.append((cid, papers))
        resolved_str = " + ".join(f"cluster {cid} -> papers {papers}" for cid, papers in all_papers)
        print(f"  RESOLVED: {resolved_str}")
    else:
        print("  (no top-level items to check)")

    print()
    print("SCATTERED (by reason):")
    for reason, n in cur.execute(
        "SELECT reason, COUNT(*) FROM synthesis_scattered WHERE run_id = ? GROUP BY reason",
        (run_id,),
    ).fetchall():
        print(f"  {reason}: {n}")
    total_scattered = cur.execute(
        "SELECT COUNT(*) FROM synthesis_scattered WHERE run_id = ?", (run_id,)
    ).fetchone()[0]
    print(f"  total: {total_scattered}")
    print("=" * 92)


# ---------------------------------------------------------------- driver
async def main():
    db = connect(DB_PATH)

    try:
        cluster_synths, camps, top, noise_ids, folded, scattered_ids = (
            await regenerate_and_verify(db)
        )
    except RuntimeError as e:
        print()
        print("!" * 92)
        print(str(e))
        print("!" * 92)
        db.close()
        return

    print()
    print("=" * 92)
    print("STEP 2: persist (idempotent per exploration_id)")
    print("-" * 92)
    replace_existing_run(db, EXPLORE_EXPLORATION_ID)
    run_id, counts = persist(db, camps, top, noise_ids, folded, scattered_ids)
    print(f"run_id={run_id}")
    for tbl, n in counts.items():
        print(f"  {tbl}: {n} row(s) inserted")

    print()
    read_back(db, run_id)

    db.close()


if __name__ == "__main__":
    asyncio.run(main())
