#!/usr/bin/env python3
"""DIAGNOSTIC (read-only, no writes): do the SCATTERED explore papers hide
coherent sub-groups that the full-set HDBSCAN missed?

Scattered = explore papers that are HDBSCAN noise (label -1, i.e. not a member
of ANY cluster row) OR members of the folded small cluster (db cluster.id=20,
exploration_id=1). Papers with no vector (e.g. id=69, no PDF) are excluded.

Nothing is written. This does not touch the real pipeline's clustering params,
does not re-cluster the full set, and does not persist anything -- it only
inspects the BGE-M3 vectors already in vec_bge_m3 for the scattered subset.
"""
import sys
from pathlib import Path

import numpy as np
from sklearn.cluster import HDBSCAN

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from backend.config import DB_PATH
from backend.db import connect

EXPLORE_EXPLORATION_ID = 1


def load_scattered_ids(db):
    cur = db.cursor()
    cur.execute("SELECT id FROM paper WHERE source = 'explore'")
    all_explore = {r[0] for r in cur.fetchall()}

    cur.execute(
        "SELECT id FROM cluster WHERE exploration_id = ?", (EXPLORE_EXPLORATION_ID,)
    )
    all_cluster_ids = [r[0] for r in cur.fetchall()]

    clustered_anywhere = set()
    for cid in all_cluster_ids:
        cur.execute("SELECT paper_id FROM paper_cluster WHERE cluster_id = ?", (cid,))
        clustered_anywhere.update(r[0] for r in cur.fetchall())

    noise_ids = sorted(all_explore - clustered_anywhere)

    # folded small cluster = db cluster.id=20 ("Cluster 0"), size<3 usable
    cur.execute("SELECT paper_id FROM paper_cluster WHERE cluster_id = 20")
    folded_members = sorted(r[0] for r in cur.fetchall())

    scattered = sorted(set(noise_ids) | set(folded_members))
    return scattered, noise_ids, folded_members


def load_meta(db, ids):
    if not ids:
        return {}
    cur = db.cursor()
    qmarks = ",".join("?" for _ in ids)
    cur.execute(
        f"SELECT id, title, abstract FROM paper WHERE id IN ({qmarks})", ids
    )
    return {r[0]: {"title": r[1], "has_abstract": bool(r[2] and r[2].strip())} for r in cur.fetchall()}


def load_vectors(db, ids):
    """Returns (present_ids, X) -- ids that actually have a vec_bge_m3 row."""
    cur = db.cursor()
    present, vecs = [], []
    for pid in ids:
        cur.execute("SELECT embedding FROM vec_bge_m3 WHERE paper_id = ?", (pid,))
        row = cur.fetchone()
        if row is not None:
            present.append(pid)
            vecs.append(np.frombuffer(row[0], dtype=np.float32))
    X = np.stack(vecs) if vecs else np.zeros((0, 1024), dtype=np.float32)
    return present, X


def cosine_sim_matrix(X):
    # X is already unit-normalized (BGE-M3 embed with normalize_embeddings=True),
    # so cosine similarity == dot product.
    return X @ X.T


def trunc(s, n=90):
    s = (s or "").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def main():
    db = connect(DB_PATH)

    # ================= STEP 0 =================
    print("=" * 92)
    print("STEP 0: assemble the scattered set")
    print("-" * 92)
    scattered_ids, noise_ids, folded_members = load_scattered_ids(db)
    meta = load_meta(db, scattered_ids)

    print(f"noise (label -1) count: {len(noise_ids)}")
    print(f"folded-cluster (db.id=20) members: {folded_members}")
    print(f"scattered set (union) count: {len(scattered_ids)}")
    print()
    for pid in scattered_ids:
        m = meta.get(pid, {})
        tag = "folded-cluster" if pid in folded_members and pid not in noise_ids else "noise"
        print(f"  [{pid}] ({tag:14}) abstract_present={m.get('has_abstract')}  {trunc(m.get('title'), 75)}")

    present_ids, X = load_vectors(db, scattered_ids)
    missing_vec = sorted(set(scattered_ids) - set(present_ids))
    print()
    print(f"vectors found in vec_bge_m3: {len(present_ids)}/{len(scattered_ids)}")
    if missing_vec:
        print(f"  EXCLUDED (no vector): {missing_vec}  "
              f"({[trunc(meta.get(p,{}).get('title'),50) for p in missing_vec]})")
    scattered_ids = present_ids  # proceed only with vectorized papers
    n = len(scattered_ids)
    print(f"proceeding with n={n} vectorized scattered papers")

    if n < 2:
        print("Too few vectorized scattered papers to analyze further.")
        db.close()
        return

    id_to_idx = {pid: i for i, pid in enumerate(scattered_ids)}
    sim = cosine_sim_matrix(X)

    # ================= STEP 1 =================
    print()
    print("=" * 92)
    print("STEP 1: pairwise near-neighbors (top-3 WITHIN scattered set)")
    print("-" * 92)
    for pid in scattered_ids:
        i = id_to_idx[pid]
        sims = [(scattered_ids[j], sim[i, j]) for j in range(n) if j != i]
        sims.sort(key=lambda t: t[1], reverse=True)
        top3 = sims[:3]
        print(f"\n  [{pid}] {trunc(meta.get(pid,{}).get('title'), 70)}")
        for nb_id, s in top3:
            print(f"      -> [{nb_id}] sim={s:.4f}  {trunc(meta.get(nb_id,{}).get('title'), 65)}")

    # ================= STEP 2 =================
    print()
    print("=" * 92)
    print("STEP 2: re-cluster the scattered subset (SIGNAL, not verdict)")
    print("-" * 92)
    print("NOTE: subset re-clustering changes local density vs the full 49-paper set,")
    print("      so any group formed here is a CANDIDATE to investigate, not a")
    print("      confirmed camp. Full-pipeline clustering params are NOT changed.")

    subset_results = {}
    for mcs in (2, 3):
        labels = HDBSCAN(min_cluster_size=mcs, copy=False).fit_predict(X)
        labels = [int(l) for l in labels]
        groups = {}
        for pid, lab in zip(scattered_ids, labels):
            if lab == -1:
                continue
            groups.setdefault(lab, []).append(pid)
        still_noise = [pid for pid, lab in zip(scattered_ids, labels) if lab == -1]

        print(f"\n--- min_cluster_size={mcs} ---")
        print(f"  #clusters formed: {len(groups)}   #still-noise: {len(still_noise)}")
        for lab, members in sorted(groups.items()):
            print(f"  GROUP {lab} (size={len(members)}):")
            for pid in members:
                print(f"      [{pid}] {trunc(meta.get(pid,{}).get('title'), 75)}")
        if still_noise:
            print(f"  still-noise ids: {still_noise}")
        subset_results[mcs] = {"groups": groups, "still_noise": still_noise}

    # ================= STEP 3 =================
    print()
    print("=" * 92)
    print("STEP 3: readout + interpretation")
    print("-" * 92)

    # coherent sub-group candidates: any HDBSCAN group of size>=3 at either setting
    candidates = []
    for mcs, res in subset_results.items():
        for lab, members in res["groups"].items():
            if len(members) >= 3:
                candidates.append((mcs, lab, members))

    if candidates:
        print("Coherent sub-group candidate(s) (size>=3) from subset HDBSCAN:")
        for mcs, lab, members in candidates:
            titles = [meta.get(p, {}).get("title") for p in members]
            print(f"  @min_cluster_size={mcs} GROUP {lab}: {members}")
            for pid, t in zip(members, titles):
                print(f"      [{pid}] {trunc(t, 80)}")
    else:
        print("No HDBSCAN group of size>=3 formed in the subset at either setting.")

    # low-resource-language suspect check: ids 35,36,37,43,44 (if present/vectorized)
    print()
    print("LOW-RESOURCE-LANGUAGE SUSPECT CHECK (papers 35,36,37,43,44):")
    lrl_ids = [p for p in (35, 36, 37, 43, 44) if p in id_to_idx]
    missing_lrl = [p for p in (35, 36, 37, 43, 44) if p not in id_to_idx]
    if missing_lrl:
        print(f"  NOTE: not in vectorized scattered set (excluded/not scattered): {missing_lrl}")
    if len(lrl_ids) >= 2:
        print("  pairwise cosine similarities:")
        for a_idx in range(len(lrl_ids)):
            for b_idx in range(a_idx + 1, len(lrl_ids)):
                a, b = lrl_ids[a_idx], lrl_ids[b_idx]
                s = sim[id_to_idx[a], id_to_idx[b]]
                print(f"      [{a}]<->[{b}]  sim={s:.4f}   "
                      f"{trunc(meta.get(a,{}).get('title'),35)} <-> {trunc(meta.get(b,{}).get('title'),35)}")
        pair_sims = [sim[id_to_idx[lrl_ids[i]], id_to_idx[lrl_ids[j]]]
                     for i in range(len(lrl_ids)) for j in range(i + 1, len(lrl_ids))]
        print(f"  mean pairwise sim among these {len(lrl_ids)}: {np.mean(pair_sims):.4f}")
    else:
        print("  fewer than 2 present -- cannot compute pairwise similarity.")

    # Bottom-line flag: coherent = candidates found via subset HDBSCAN (size>=3),
    # OR strong reciprocal top-3 near-neighbor mutual grouping (eyeballed above).
    print()
    print("-" * 92)
    if candidates:
        named = sorted({pid for _, _, members in candidates for pid in members})
        print(f"HIDDEN SUBGROUPS FOUND: {named}  -> suggests clustering-tune worth trying")
    else:
        print("NO COHERENT SUBGROUPS  -> 2 camps is honest; persist as-is")
    print("=" * 92)

    db.close()


if __name__ == "__main__":
    main()
