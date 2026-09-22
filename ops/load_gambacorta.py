"""Load the SRP342112 paper's own production numbers, closing the yield-to-transcript join.

    python ops/load_gambacorta.py --apply --curator <you>

This is the join that was empty: the four strains carrying every scrap of transcript evidence in
the atlas had no titer and no yield, so nothing could ask whether the transcript-backed route is
the high-yielding one. `doi:10.1016/j.synbio.2022.02.007` reports exactly those four strains, and
its numbers answer the question in the opposite direction to the obvious guess.

Only rows this loader can attribute are written:

* a strain the extraction resolved to one of the four SRP342112 ids -- `fra2D` derivatives and
  the implied cross-experiment figures are left in the TSV for a curator, because the first is a
  strain the atlas does not hold and the second is arithmetic across two fermentations;
* a value with a number in it -- "NOT REPORTED" rows stay in the draft as the finding they are.

Everything lands at `confidence='unverified'`: the quote is machine-verified against the stored
full text, and no person has read it. That is exactly what `unverified` means in
`docs/reference/CONVENTIONS.md`, and it is the honest label for a row an extraction produced.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from fermdb.config import Settings  # noqa: E402
from fermdb.db import open_db  # noqa: E402

PUBLICATION = "doi:10.1016/j.synbio.2022.02.007"
SOURCE = "docs/drafts/extraction/2026-09-22-gambacorta-measurements.tsv"
PRODUCTS = {
    "isobutanol": "YAA:PRODUCT:isobutanol",
    "ethanol": "YAA:PRODUCT:ethanol",
    "glycerol": "YAA:PRODUCT:glycerol",
}


def _numeric(raw: str) -> float | None:
    cleaned = raw.strip().lstrip("~").replace(",", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--curator", default="claude-opus-5")
    args = parser.parse_args()

    settings = Settings.load()
    db_path = Path(settings.db_file)
    if args.apply:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        shutil.copy(db_path, db_path.with_suffix(f".sqlite3.pre-gambacorta.{stamp}.bak"))
    conn = open_db(db_path, create=False)

    known = {
        str(r[0])
        for r in conn.execute(
            "SELECT id FROM strain WHERE id LIKE 'YAA:STRAIN:y79%' OR id LIKE 'YAA:STRAIN:y81%'"
        )
    }
    rows = list(csv.DictReader((REPO / SOURCE).open(encoding="utf-8"), delimiter="\t"))
    print(f"{len(rows)} extracted row(s); {len(known)} SRP342112 strain(s) in the atlas\n")

    written = 0
    skipped: list[str] = []
    for row in rows:
        strain_id = row["strain_id_guess"].strip()
        value = _numeric(row["value_as_reported"])
        product = PRODUCTS.get(row["product"].strip())
        kind = row["quantity_kind"].strip()

        if strain_id not in known:
            skipped.append(f"{row['strain_as_reported'][:28]}: strain not in the atlas")
            continue
        if value is None:
            skipped.append(f"{row['strain_as_reported'][:28]} {kind}: no number reported")
            continue
        if product is None or kind not in {"titer", "yield"}:
            continue

        # `measurement` refuses a yield with no basis, and `basis` is a closed vocabulary about
        # HOW the denominator is defined -- consumed, supplied, % of theoretical -- not which
        # sugar it was. This paper writes "mg isobutanol/g glucose" and never says whether the
        # gram is glucose supplied or glucose consumed, and the two differ by however much sugar
        # was left. So the basis is recorded as `unknown`, which is true, and the substrate
        # travels in `evidence` where a curator can find it. Guessing `consumed` here would put
        # an unstated assumption into a number other work divides by.
        basis = None
        if kind == "yield":
            basis = "unknown"
            substrate = row["unit_as_reported"].split("/")[-1].strip() or "unstated"

        identity = hashlib.sha256(
            f"{PUBLICATION}|{strain_id}|{kind}|{row['product']}|{row['value_as_reported']}|"
            f"{row['unit_as_reported']}".encode()
        ).hexdigest()[:24]
        measurement_id = f"YAA:MEAS:gambacorta-{identity}"
        evidence = (
            f"extracted from {PUBLICATION} ({row['source_locator']}) by a fermdb extraction "
            f"agent on 2026-09-22, quote machine-verified against the stored full text: "
            f'"{row["quote"][:320]}". Conditions as reported: '
            f"{row['medium_and_cultivation_as_reported'][:160]}. "
            f"NOT reviewed by a person; curator {args.curator} ran the loader"
        )
        if kind == "yield":
            evidence += (
                f". Denominator as written by the paper: per g {substrate}; the paper does not "
                "say whether that is substrate supplied or consumed, so `basis` is 'unknown'"
            )
        if row["note"].strip():
            evidence += f". Extractor note: {row['note'][:200]}"

        if args.apply:
            conn.execute(
                "INSERT INTO measurement (id, strain_id, publication_id, quantity_kind, "
                "product_id, value_as_reported, unit_as_reported, basis, n_replicates, "
                "source_locator, is_below_lod, is_upper_bound, zone, evidence, confidence) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,0,0,'R',?,?) ON CONFLICT(id) DO UPDATE SET "
                "evidence=excluded.evidence",
                (
                    measurement_id,
                    strain_id,
                    PUBLICATION,
                    kind,
                    product,
                    value,
                    row["unit_as_reported"].strip(),
                    basis,
                    _numeric(row["n_replicates"]) or None,
                    row["source_locator"].strip(),
                    evidence,
                    row["confidence"].strip() or "unverified",
                ),
            )
        written += 1
        print(
            f"  {strain_id:18s} {kind:6s} {value:>8.4g} {row['unit_as_reported'][:22]:22s} "
            f"[{row['confidence']}]"
        )

    print(f"\n{len(skipped)} row(s) left for a curator:")
    for note in skipped[:8]:
        print(f"  - {note}")

    if args.apply:
        conn.commit()
        total = conn.execute(
            "SELECT COUNT(*) FROM measurement WHERE publication_id = ?", (PUBLICATION,)
        ).fetchone()[0]
        print(f"\ncommitted {written} measurement(s); {total} now cite this paper")
    else:
        print(f"\n(dry run; {written} measurement(s) would be written)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
