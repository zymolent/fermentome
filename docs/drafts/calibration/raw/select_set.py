"""Freeze the 20-paper gold-standard calibration set (D8 stratification).

Content-blind selection rule, fixed BEFORE any model is run (PLAN.md S.2):
  eligible  = stored_fulltext AND media_type application/xml (JATS)
              AND no existing `extraction` row
              AND 10_000 <= len(raw xml) <= 400_000   (operational size band, pre-registered)
  strata    = disjoint, by triage family membership
  order     = publication_id ascending (lexicographic, content-independent)
  take      = first k of each stratum
"""

import json
import sqlite3
from pathlib import Path

DB = Path(r"C:\Users\kangk\fermdb-data\fermdb.sqlite3")
DATA = Path(r"C:\Users\kangk\fermdb-data")

MIN_CHARS, MAX_CHARS = 10_000, 400_000

db = sqlite3.connect(DB)
c = db.cursor()

extracted = {r[0] for r in c.execute("select distinct publication_id from extraction").fetchall()}

fams: dict[str, set[str]] = {}
for pid, fam in c.execute("select publication_id, family from screening_record").fetchall():
    fams.setdefault(pid, set()).add(fam)

rows = c.execute(
    "select publication_id, content_path, media_type from fulltext_asset "
    "where storage_state='stored_fulltext' and media_type='application/xml'"
).fetchall()

meta = {
    r[0]: (r[1], r[2], r[3])
    for r in c.execute("select id, doi, title, year from publication").fetchall()
}

ISO = {"isobutanol_all", "isobutanol_production", "isobutanol_yeast", "isobutanol_mitochondria"}
MT = {"mtdna_engineering_yeast", "mtdna_methods_yeast"}
ETH = {"ethanol_scerevisiae_prod_ferm_tol", "ethanol_mitochondria_yeast"}

strata: dict[str, list] = {"IY": [], "IO": [], "MT": [], "ET": []}

for pid, cpath, _mt in rows:
    if pid in extracted:
        continue
    p = DATA / cpath.replace("\\", "/")
    if not p.exists():
        continue
    n = p.stat().st_size
    if not (MIN_CHARS <= n <= MAX_CHARS):
        continue
    f = fams.get(pid, set())
    if not f:
        continue
    rec = (pid, n, meta.get(pid, (None, None, None)))
    if "isobutanol_yeast" in f or "isobutanol_mitochondria" in f:
        strata["IY"].append(rec)
    elif f & ISO:
        strata["IO"].append(rec)
    elif f & MT:
        strata["MT"].append(rec)
    elif f & ETH:
        strata["ET"].append(rec)

want = {"IY": 8, "IO": 4, "MT": 4, "ET": 4}
chosen: dict[str, list] = {}
for k, v in strata.items():
    v.sort(key=lambda r: r[0])
    chosen[k] = v[: want[k]]
    print(f"{k}: pool={len(v)} taken={len(chosen[k])}")

# interleave so any prefix stays stratified: IY IY IO MT ET, x4
order = []
for i in range(4):
    order.append(chosen["IY"][2 * i])
    order.append(chosen["IY"][2 * i + 1])
    order.append(chosen["IO"][i])
    order.append(chosen["MT"][i])
    order.append(chosen["ET"][i])

labels = ["IY", "IY", "IO", "MT", "ET"] * 4
out = []
for rank, (rec, lab) in enumerate(zip(order, labels), start=1):
    pid, n, (doi, title, year) = rec
    out.append(
        {
            "rank": rank,
            "stratum": lab,
            "publication_id": pid,
            "doi": doi,
            "year": year,
            "title": title,
            "xml_bytes": n,
        }
    )
    print(f"{rank:2d} {lab} {pid:45s} {n:>8d} {(title or '')[:60]}")

Path(r"C:\Users\kangk\AppData\Local\Temp\claude\d--project-yeast-alcohol-db\aa10009e-5f06-4ad6-a7a6-916cbbe63a58\scratchpad\frozen20.json").write_text(
    json.dumps(out, indent=2), encoding="utf-8"
)
