"""Recall comparison: what the local tier failed to propose that the capable tier proposed.

Also re-runs the repo's own `verify_span` over every proposed span of both tiers, against the
same canonical source text the harness recorded offsets against.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, r"D:\project\yeast-alcohol-db\src")

SCRATCH = Path(
    r"C:\Users\kangk\AppData\Local\Temp\claude\d--project-yeast-alcohol-db"
    r"\aa10009e-5f06-4ad6-a7a6-916cbbe63a58\scratchpad"
)

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402
from fermdb.extract.harness import load_source_text  # noqa: E402
from fermdb.llm.validate import Span, canonical_source_text, verify_span  # noqa: E402


def norm(s: object) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(s or "").lower()).strip()


KEY = {
    "strains": lambda r: norm(r.get("name_as_reported")),
    "modifications": lambda r: norm(r.get("target_as_reported")) + "|" + norm(r.get("modification_type")),
    "measurements": lambda r: norm(r.get("product_as_reported")) + "|" + norm(r.get("value")),
    "conditions": lambda r: norm(r.get("facet")) + "|" + norm(r.get("value_as_reported"))[:40],
    "bottlenecks": lambda r: norm(r.get("description_as_reported"))[:40],
    "pathway_configurations": lambda r: norm(r.get("name_as_reported"))[:40],
    "co_reported_higher_alcohols": lambda r: norm(r.get("product_as_reported")) + "|" + norm(r.get("value")),
}

FACET_KINDS = {
    "measurements": "measurement",
    "strains": "strain",
    "modifications": "modification",
    "conditions": "condition facet",
    "bottlenecks": "bottleneck",
    "pathway_configurations": "pathway configuration",
    "co_reported_higher_alcohols": "co-reported alcohol",
}


def load(tier: str) -> dict[str, dict]:
    d = SCRATCH / f"out_{tier}"
    out = {}
    if d.exists():
        for p in sorted(d.glob("*.json")):
            r = json.loads(p.read_text(encoding="utf-8"))
            out[r["publication_id"]] = r
    return out


def span_of(rec: dict) -> dict | None:
    s = rec.get("span")
    return s if isinstance(s, dict) else None


def overlaps(a: dict, b: dict) -> bool:
    return a["char_start"] < b["char_end"] and b["char_start"] < a["char_end"]


def main() -> int:
    loc, cap = load("local"), load("capable")
    settings = Settings.load()
    conn = open_db(settings.db_file)

    shared = [p for p in cap if p in loc]
    print(f"papers with BOTH arms complete: {len(shared)}")
    print(f"capable-only: {len(cap) - len(shared)}   local-only: {len(loc) - len(shared)}\n")

    # ---------------- span verification, both tiers, every paper it has -------------------
    print("=== SPAN VERIFICATION (repo verify_span, canonical source text) ===")
    span_stats: dict[str, dict[str, int]] = {}
    for tier, data in (("local", loc), ("capable", cap)):
        st = {"total": 0, "ok": 0, "fail": 0}
        codes: dict[str, int] = {}
        for pid, r in data.items():
            if r["status"] != "ok":
                continue
            raw, _ = load_source_text(conn, settings, publication_id=pid)
            canon = canonical_source_text(raw)
            for _kind, _i, rec in r["records"]:
                sp = span_of(rec)
                if not sp:
                    continue
                st["total"] += 1
                s = Span(
                    quote=sp["quote"],
                    char_start=sp["char_start"],
                    char_end=sp["char_end"],
                    section=sp.get("section"),
                )
                # The harness records offsets against the text it was handed (raw). Verify
                # against that first; canonical is the fallback, not the source of record.
                v = verify_span(raw, s)
                if not v.ok:
                    v2 = verify_span(canon, s)
                    if v2.ok:
                        v = v2
                if v.ok:
                    st["ok"] += 1
                else:
                    st["fail"] += 1
                    # quote_absent_from_source in BOTH forms = the quote is not in the paper
                    in_raw = sp["quote"] in raw or sp["quote"] in canon
                    key = (v.reason or "?") + ("" if in_raw else " [QUOTE NOT IN PAPER]")
                    codes[key] = codes.get(key, 0) + 1
        span_stats[tier] = st
        pct = 100 * st["fail"] / st["total"] if st["total"] else 0
        print(f"  {tier:8s} spans={st['total']:4d} resolve={st['ok']:4d} FAIL={st['fail']:4d} ({pct:.1f}%)  {codes}")
    print()

    # repair notes = offsets the model got wrong but quote present
    print("=== OFFSET REPAIRS (model's own offsets wrong, quote present) ===")
    for tier, data in (("local", loc), ("capable", cap)):
        tot = rep = 0
        for r in data.values():
            if r["status"] != "ok":
                continue
            tot += r["record_count"]
            rep += sum(1 for n in r["notes"] if n[1] == "span_offsets_repaired")
        print(f"  {tier:8s} records={tot:4d} offsets_repaired={rep:4d} ({100*rep/tot if tot else 0:.0f}%)")
    print()

    if not shared:
        print("NO PAPER HAS BOTH ARMS -- no recall table can be computed.")
        conn.close()
        return 0

    # ---------------- recall ---------------------------------------------------------------
    print("=== RECALL: capable-proposed records the local tier did NOT propose ===")
    by_kind: dict[str, dict[str, int]] = {}
    per_paper = []
    for pid in shared:
        c, l = cap[pid], loc[pid]
        if c["status"] != "ok":
            continue
        lrecs: dict[str, list[dict]] = {}
        if l["status"] == "ok":
            for k, _i, rec in l["records"]:
                lrecs.setdefault(k, []).append(rec)
        hit = miss = 0
        for k, _i, crec in c["records"]:
            cands = lrecs.get(k, [])
            ck, cs = KEY.get(k, lambda r: norm(r))(crec), span_of(crec)
            found = False
            for lrec in cands:
                if ck and ck == KEY.get(k, lambda r: norm(r))(lrec):
                    found = True
                    break
                ls = span_of(lrec)
                if cs and ls and overlaps(cs, ls):
                    found = True
                    break
            d = by_kind.setdefault(k, {"capable": 0, "recalled": 0, "local_only": 0})
            d["capable"] += 1
            if found:
                d["recalled"] += 1
                hit += 1
            else:
                miss += 1
        # local proposals with no capable counterpart
        crecs: dict[str, list[dict]] = {}
        for k, _i, rec in c["records"]:
            crecs.setdefault(k, []).append(rec)
        for k, _i, lrec in (l["records"] if l["status"] == "ok" else []):
            lk, ls = KEY.get(k, lambda r: norm(r))(lrec), span_of(lrec)
            found = False
            for crec in crecs.get(k, []):
                if lk and lk == KEY.get(k, lambda r: norm(r))(crec):
                    found = True
                    break
                cs2 = span_of(crec)
                if ls and cs2 and overlaps(ls, cs2):
                    found = True
                    break
            if not found:
                by_kind.setdefault(k, {"capable": 0, "recalled": 0, "local_only": 0})["local_only"] += 1
        per_paper.append((c["rank"], c["stratum"], pid, c["record_count"],
                          l["record_count"] if l["status"] == "ok" else 0, hit, miss,
                          l["status"], round(c["seconds"]), round(l["seconds"])))

    print(f"{'#':>2} {'st':3} {'paper':40} {'cap':>4} {'loc':>4} {'hit':>4} {'MISS':>5} {'cap_s':>6} {'loc_s':>6} local_status")
    for rank, st, pid, cn, ln, hit, miss, lst, cs_, ls_ in sorted(per_paper):
        print(f"{rank:2d} {st:3} {pid[:40]:40} {cn:4d} {ln:4d} {hit:4d} {miss:5d} {cs_:6d} {ls_:6d} {lst}")
    print()
    print(f"{'kind':26} {'capable':>8} {'recalled':>9} {'MISSED':>7} {'recall':>7} {'local_only':>11}")
    tc = tr = 0
    for k in sorted(by_kind, key=lambda x: -by_kind[x]["capable"]):
        d = by_kind[k]
        tc += d["capable"]
        tr += d["recalled"]
        rc = 100 * d["recalled"] / d["capable"] if d["capable"] else float("nan")
        print(f"{FACET_KINDS.get(k,k):26} {d['capable']:8d} {d['recalled']:9d} {d['capable']-d['recalled']:7d} {rc:6.0f}% {d['local_only']:11d}")
    print(f"{'TOTAL':26} {tc:8d} {tr:9d} {tc-tr:7d} {100*tr/tc if tc else 0:6.0f}%")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
