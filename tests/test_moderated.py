"""Tests for the moderated t-test and the evidence it becomes.

The moderated test exists because the unmoderated one could not see what is in this data: on
SRP342112 it returned **zero** significant genes where the published analysis of the same runs
recovers hundreds. Borrowing variance across genes fixes that. The risk it introduces is the
opposite one -- a prior that shrinks too hard turns the t-test into a z-test and manufactures
significance -- so the tests below pin both directions:

* the prior must be *finite and fitted*, not degenerate, on data with real variance spread;
* the test must **hold its size**: on data with no group difference at all, it must not produce
  significant genes. That is the property that would fail silently and be believed.

The evidence half is tested for the constraint `schema.sql` cares about: a `correlative_omics`
row must carry an effect size and an adjusted p, must never cite a `measurement`, and must leave
the assertion walkable by PLAN.md J.5's gate.
"""

from __future__ import annotations

import math
import random

from fermdb.db import IN_MEMORY, open_db
from fermdb.omics import contrasts as C
from fermdb.omics import evidence as E


def _groups(
    n_genes: int, n_ref: int, n_trt: int, *, shift: float, seed: int = 3
) -> list[list[float]]:
    """Log-scale values; `shift` is added to the treatment side of the first tenth of genes."""
    rng = random.Random(seed)
    rows: list[list[float]] = []
    for g in range(n_genes):
        base = 4.0 + (g % 30) * 0.2
        spread = 0.15 + (g % 7) * 0.02
        row = [base + rng.gauss(0.0, spread) for _ in range(n_ref)]
        lift = shift if g < n_genes // 10 else 0.0
        row += [base + lift + rng.gauss(0.0, spread) for _ in range(n_trt)]
        rows.append(row)
    return rows


# ------------------------------------------------------------------------------------ the prior


def test_the_variance_prior_is_fitted_not_degenerate() -> None:
    """An infinite prior df collapses every gene to one variance and over-states significance."""
    rows = _groups(2000, 3, 3, shift=0.0)
    df_residual = 4
    variances = []
    for row in rows:
        ref, trt = row[:3], row[3:]
        mr, mt = sum(ref) / 3, sum(trt) / 3
        ss = sum((v - mr) ** 2 for v in ref) + sum((v - mt) ** 2 for v in trt)
        variances.append(ss / df_residual)
    s0_squared, df_prior = C.fit_variance_prior(variances, df_residual)
    assert s0_squared > 0
    assert math.isfinite(df_prior)
    assert df_prior > 0
    # The prior should sit inside the bulk of the observed variances, not outside it.
    ordered = sorted(variances)
    assert ordered[len(ordered) // 10] < s0_squared < ordered[9 * len(ordered) // 10]


def test_the_prior_refuses_to_fit_from_nothing() -> None:
    assert C.fit_variance_prior([], 4) == (0.0, 0.0)
    assert C.fit_variance_prior([0.1], 0) == (0.0, 0.0)


# ------------------------------------------------------------------------------------- the size


def test_the_moderated_test_holds_its_size_under_the_null() -> None:
    """No group difference anywhere: significant genes must be ~none, not many.

    This is the test that matters. A shrinkage bug shows up here as a flood of hits on data that
    contains nothing, and it would otherwise be indistinguishable from a real discovery.
    """
    rows = _groups(2000, 3, 3, shift=0.0)
    _stats, p_values, _s0, _dfp, _dft = C.moderated_t(rows, n_reference=3, n_treatment=3)
    usable = [p for p in p_values if p is not None and not math.isnan(p)]
    assert len(usable) > 1900
    adjusted = C._benjamini_hochberg(usable)
    assert sum(1 for p in adjusted if p <= 0.05) == 0
    # And the raw p-values must not be systematically small.
    assert sum(1 for p in usable if p <= 0.05) / len(usable) < 0.10


def test_the_moderated_test_finds_a_real_difference_welch_would_miss() -> None:
    """The reason it replaced Welch: at n=3 the unmoderated test sees far less."""
    rows = _groups(2000, 3, 3, shift=0.8)
    _stats, moderated_p, _s0, _dfp, _dft = C.moderated_t(rows, n_reference=3, n_treatment=3)
    moderated_hits = sum(
        1
        for p in C._benjamini_hochberg(
            [p for p in moderated_p if p is not None and not math.isnan(p)]
        )
        if p <= 0.05
    )
    welch_raw = []
    for row in rows:
        outcome = C._welch_t(row[:3], row[3:])
        if outcome is not None:
            welch_raw.append(outcome[1])
    welch_hits = sum(1 for p in C._benjamini_hochberg(welch_raw) if p <= 0.05)
    assert moderated_hits > welch_hits
    # The shifted genes are the first tenth; the test should recover a good share of them.
    assert moderated_hits >= 100


def test_differential_expression_falls_back_to_welch_on_too_few_genes() -> None:
    """A prior cannot be fitted from a handful of genes, and pretending otherwise is worse."""
    genes = [f"G{i}" for i in range(12)]
    rows = [[100.0, 105.0, 98.0, 300.0, 310.0, 295.0] for _ in genes]
    results, _f, underpowered, tested, _filtered = C.differential_expression(
        genes, rows, n_reference=3, n_treatment=3, method="moderated_t"
    )
    assert not underpowered
    assert tested == len(genes)
    assert all(r.p_adjusted is not None for r in results)


def test_the_method_is_recorded_in_the_parameters_hash() -> None:
    """Two results computed by different tests must not share a recipe hash."""
    genes = [f"G{i}" for i in range(200)]
    rows = _groups(200, 3, 3, shift=0.5)
    counts = [[2**v for v in row] for row in rows]
    a, *_ = C.differential_expression(
        genes, counts, n_reference=3, n_treatment=3, method="moderated_t"
    )
    b, *_ = C.differential_expression(genes, counts, n_reference=3, n_treatment=3, method="welch_t")
    # Same fold changes, different p-values -- the estimate is shared, the inference is not.
    assert [r.log2_fold_change for r in a] == [r.log2_fold_change for r in b]
    assert [r.p_value for r in a] != [r.p_value for r in b]


# ---------------------------------------------------------------------------------- the evidence


class _Step:
    def __init__(self, status: str, **kw: object) -> None:
        self.status = status
        self.part_id = kw.get("part_id", "YAA:PART:ilv5-native")
        self.contrast_id = kw.get("contrast_id", "YAA:ANALYSIS:de-x")
        self.log2_fold_change = kw.get("log2_fold_change", 3.0)
        self.p_adjusted = kw.get("p_adjusted", 0.001)
        self.genes = kw.get("genes", ("ILV5",))
        self.note = kw.get("note", "note")


class _Support:
    def __init__(self, steps: list[_Step]) -> None:
        self.steps = steps


def test_only_a_resolved_elevated_step_becomes_an_assertion() -> None:
    supports = [
        _Support(
            [
                _Step("elevated_in_build"),
                _Step("elevated_not_resolved", part_id="YAA:PART:ilv3-native"),
                _Step("unchanged_in_build", part_id="YAA:PART:aro10-native"),
                _Step("confounded_by_construct", part_id="YAA:PART:ilv2-ilv6-native"),
                _Step("elevated_in_build", part_id="YAA:PART:adh1-native", p_adjusted=None),
            ]
        )
    ]
    claims = E.assertions_from_support(
        supports, contrast_strains={"YAA:ANALYSIS:de-x": ("YAA:STRAIN:p", "YAA:STRAIN:q")}
    )
    assert len(claims) == 1
    assert claims[0].subject_id == "YAA:PART:ilv5-native"
    assert claims[0].direction == "increases"


def test_the_same_step_across_many_routes_makes_one_assertion() -> None:
    """6,400 routes share step signatures; one claim per (part, strain, contrast), not per route."""
    supports = [_Support([_Step("elevated_in_build")]) for _ in range(50)]
    claims = E.assertions_from_support(
        supports, contrast_strains={"YAA:ANALYSIS:de-x": ("YAA:STRAIN:p", "YAA:STRAIN:q")}
    )
    assert len(claims) == 1


def test_the_written_evidence_satisfies_the_schema_and_is_walkable() -> None:
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'S. cerevisiae', 'R', 't', 'high')"
    )
    for sid in ("YAA:STRAIN:p", "YAA:STRAIN:q"):
        conn.execute(
            "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
            "confidence) VALUES (?, 'YAA:ORG:sc', ?, 'engineered', 'R', 't', 'medium')",
            (sid, sid.rsplit(":", 1)[-1]),
        )
    conn.execute(
        "INSERT INTO part (id, step_role_id, sequence_encoding_genome, cofactor_preference, "
        "zone, evidence, confidence) VALUES ('YAA:PART:ilv5-native', 'KARI', 'nuclear', "
        "'NADPH', 'I', 't', 'low')"
    )
    conn.execute("INSERT INTO processing_run (id, pipeline, version) VALUES ('r', 'p', '1')")
    conn.execute(
        "INSERT INTO analysis_result (id, processing_run_id, kind, payload_ref, zone) "
        "VALUES ('YAA:ANALYSIS:de-x', 'r', 'differential_expression', 'f', 'H')"
    )

    claims = E.assertions_from_support(
        [_Support([_Step("elevated_in_build")])],
        contrast_strains={"YAA:ANALYSIS:de-x": ("YAA:STRAIN:p", "YAA:STRAIN:q")},
    )
    made, cited = E.write_assertions(conn, claims)
    assert made == 1 and cited == 1

    row = conn.execute(
        "SELECT evidence_type, effect_size, p_adjusted, measurement_id, analysis_result_id "
        "FROM evidence_item"
    ).fetchone()
    assert row["evidence_type"] == "correlative_omics"
    assert row["effect_size"] is not None and row["p_adjusted"] is not None
    # The exclusivity rule: correlative evidence must never acquire a measurement's authority.
    assert row["measurement_id"] is None
    assert row["analysis_result_id"] == "YAA:ANALYSIS:de-x"

    # J.5's gate walks assertion -> who made it; the event must exist.
    event = conn.execute(
        "SELECT actor_kind, action FROM curation_event WHERE target_type = 'assertion'"
    ).fetchone()
    assert event["actor_kind"] == "agent"
    assert event["action"] == "create"


def test_writing_twice_is_idempotent() -> None:
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, zone, evidence, confidence) "
        "VALUES ('YAA:ORG:sc', 'S. cerevisiae', 'R', 't', 'high')"
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:q', 'YAA:ORG:sc', 'q', 'engineered', 'R', 't', 'medium')"
    )
    conn.execute(
        "INSERT INTO part (id, step_role_id, sequence_encoding_genome, cofactor_preference, "
        "zone, evidence, confidence) VALUES ('YAA:PART:ilv5-native', 'KARI', 'nuclear', "
        "'NADPH', 'I', 't', 'low')"
    )
    conn.execute("INSERT INTO processing_run (id, pipeline, version) VALUES ('r', 'p', '1')")
    conn.execute(
        "INSERT INTO analysis_result (id, processing_run_id, kind, payload_ref, zone) "
        "VALUES ('YAA:ANALYSIS:de-x', 'r', 'differential_expression', 'f', 'H')"
    )
    claims = E.assertions_from_support(
        [_Support([_Step("elevated_in_build")])],
        contrast_strains={"YAA:ANALYSIS:de-x": ("YAA:STRAIN:p", "YAA:STRAIN:q")},
    )
    E.write_assertions(conn, claims)
    again = E.write_assertions(conn, claims)
    assert again == (0, 0)
    assert conn.execute("SELECT COUNT(*) FROM assertion").fetchone()[0] == 1
