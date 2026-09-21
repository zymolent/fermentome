"""Tests for `fermdb.metabolic.recall` — PLAN.md phase 3's recall clause.

    *"the enumerator re-discovers every published configuration (recall test against phase 1)"*

`pathway_configuration` holds **0 rows** in the live atlas, so the clause itself cannot be
evaluated today. What CAN be tested — and what these tests do — is that the harness is correct and
correctly strict for the moment those rows land, and that it says "cannot be evaluated" rather
than a number when it has nothing to measure.

The configurations built here are not invented. Each is copied from a real
`pathway_configurations` extraction payload sitting in `curation_task` in the live atlas, run
through the same `description` shape `curate/promote.py::_configuration_description` writes. They
are the vocabulary the harness has to survive: `"ILV genes"`, `"LlAdhA RE1"`, `"ADH7"`,
`"2-ketoacid decarboxylase (KDC) from Lactococcus lactis"`, an `E. coli` host, a
`compartment_strategy` of `"unknown"`.

THE PROPERTY UNDER TEST IS STRICTNESS. A matching rule that is too loose reports a recall the
atlas has not earned, so most of what follows is a test that something does NOT match.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.metabolic.curated import load_parts
from fermdb.metabolic.recall import (
    ENZYME_ALIASES,
    MATCHING_RULE,
    Configuration,
    classify,
    describe_report,
    enzyme_entries,
    gene_index,
    load_configurations,
    recall_report,
    resolve_roles,
)
from fermdb.metabolic.routes import STEP_ORDER, enumerate_routes

PATHS_FILE = Path(__file__).resolve().parents[1] / "env" / "paths.yaml"

_YEAST = "YAA:ORG:saccharomyces-cerevisiae-s288c"
_ECOLI = "YAA:ORG:ecoli-k12-mg1655"


@pytest.fixture(scope="module")
def parts() -> tuple:
    return load_parts(Settings.load(paths_file=PATHS_FILE, env={}))


@pytest.fixture(scope="module")
def routes(parts: tuple) -> list:
    return enumerate_routes(parts)


def _configuration(
    enzymes: list[str] | None,
    *,
    strategy: str | None = "C_mitochondrial_ehrlich",
    localization: str = "",
    organism: str | None = _YEAST,
    host: str | None = "YAA:STRAIN:fx",
    name: str = "fixture configuration",
) -> Configuration:
    """A configuration whose `description` is built the way `promote.py` builds one."""
    bits: list[str] = []
    if enzymes:
        bits.append("enzymes as reported: " + ", ".join(enzymes))
    if localization:
        bits.append(f"localization as reported: {localization}")
    return Configuration(
        id="YAA:PCFG:test",
        name=name,
        compartment_strategy_id=strategy,
        host_strain_id=host,
        host_organism_id=organism if host else None,
        host_organism_name="test organism" if host else None,
        description="; ".join(bits),
    )


def _verdict(config: Configuration, parts: tuple, routes: list) -> object:
    return classify(config, parts, routes, chassis_organism_id=_YEAST)


# ------------------------------------------------------------------ the rule is inspectable


def test_every_outcome_the_harness_can_reach_names_a_clause_of_the_written_rule() -> None:
    """The rule is data, not prose in a docstring, precisely so it cannot drift from the code.

    If someone adds a branch to `classify` without adding a clause, `_CLAUSE_BY_NAME[...]` raises
    on `.outcome` — but a clause that exists and is never reached is the quieter rot, so both
    directions are asserted below.
    """
    names = [clause.name for clause in MATCHING_RULE]
    assert len(names) == len(set(names)), "a clause name is the key a verdict is looked up by"
    assert {c.outcome for c in MATCHING_RULE} == {"matched", "missed", "not_evaluable"}
    assert sum(1 for c in MATCHING_RULE if c.outcome == "matched") == 1, (
        "exactly one clause may declare a match, or the rule has two ways to say yes"
    )
    for clause in MATCHING_RULE:
        assert len(clause.text) > 120, f"{clause.name} is not defended, only named"


def test_every_clause_of_the_rule_is_reachable(parts: tuple, routes: list) -> None:
    """One configuration per clause, so no clause is dead text in a document nobody tests."""
    cases = {
        "strategy_not_enumerable": _configuration(["ILV2"], strategy="unknown"),
        "host_not_recorded": _configuration(["ILV2"], host=None),
        "host_outside_enumeration": _configuration(["alsS"], organism=_ECOLI),
        "no_enzyme_set_recorded": _configuration(None, localization="in the mitochondria"),
        "matched": _configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH6"]),
        # ADH2 rather than ADH7: ADH7 was this exemplar until it was curated into the catalog
        # from 10.1016/j.cels.2019.10.006, which is the worklist working. ADH2 is the next real
        # yeast alcohol dehydrogenase the catalog does not carry.
        "catalog_gap": _configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH2"]),
        "under_specified": _configuration(["ILV2", "ILV5", "ILV3", "KDC", "ADH"]),
    }
    assert set(cases) == {clause.name for clause in MATCHING_RULE}
    for expected, config in cases.items():
        assert _verdict(config, parts, routes).clause == expected, expected


# ---------------------------------------------------------------- where the enzyme names come from


def test_the_localization_prose_is_never_mined_for_enzyme_names() -> None:
    """The single most dangerous loosening available, and it is refused.

    The real payload for the ValC-dependent pathway says the build works *by circumventing* Bat1p
    and Bat2p; another names Cox4, which is a targeting leader and not a pathway enzyme. A rule
    that scanned the whole description would credit a build with enzymes it deliberately removed.
    """
    description = (
        "enzymes as reported: ILV2, ILV5; localization as reported: mitochondrial KIV "
        "converted to valine by Bat1p, valine exported by ValC and deaminated by Bat2p in the "
        "cytosol, using the Cox4 leader and ARO10 nowhere"
    )
    assert enzyme_entries(description) == ("ILV2", "ILV5")
    assert "ARO10" not in " ".join(enzyme_entries(description))


def test_a_description_with_no_enzyme_segment_yields_nothing_rather_than_a_guess() -> None:
    """The mini-atlas fixture's configuration is hand-written prose with no enzyme segment. It
    must come back empty rather than being parsed hopefully."""
    assert enzyme_entries("Fixture configuration: AHAS/KARI/DHAD in the mitochondrial matrix") == ()
    assert enzyme_entries("") == ()


# ------------------------------------------------------------------------ resolution is strict


def test_resolution_is_exact_token_equality_never_substring(parts: tuple) -> None:
    """ADH2 contains 'ADH' and is a real yeast alcohol dehydrogenase that the catalog does not
    carry. A substring rule would resolve it to Adh1, Adh6 or Adh7 and report a build the
    enumerator cannot express as re-discovered.

    This test was written with ADH7 in that slot, and ADH7 is now a catalog part — curated from
    10.1016/j.cels.2019.10.006, which is the paper the recall harness named it from. So the
    exemplar moved to the next real absentee rather than the property being retired: the danger is
    the shape 'a name that ends in a symbol the catalog has', not any one gene, and the catalog
    filling up is exactly when a substring rule starts finding false matches.
    """
    resolution = resolve_roles(["ADH2"], parts)
    assert resolution.unrecognised == ("ADH2",)
    assert not any(role.filled for role in resolution.roles)
    # The gene that replaced it as the exemplar must itself still resolve exactly.
    assert dict((r.role, r.part_ids) for r in resolve_roles(["ADH7"], parts).roles)["ADH"] == (
        "adh7_native",
    )


def test_an_alias_is_a_named_exception_and_not_a_prefix_rule(parts: tuple) -> None:
    """`LlAdhA` is in the table with its reason. `XxAdhA` is not, and must stay unrecognised —
    that is the difference between a curated exception and a substring match wearing a hat."""
    assert "lladha" in ENZYME_ALIASES
    resolved = resolve_roles(["LlAdhA RE1"], parts)
    assert dict((r.role, r.part_ids) for r in resolved.roles)["ADH"] == ("adha_lactococcus",)
    assert resolve_roles(["XxAdhA"], parts).unrecognised == ("XxAdhA",)


def test_a_shared_gene_symbol_resolves_ambiguously_rather_than_picking_one(parts: tuple) -> None:
    """Four KARI parts carry the gene symbol `ilvC`, and they differ by exactly the NADPH/NADH
    question the whole atlas is about. The harness reports the ambiguity; it does not resolve it,
    because deciding that a paper's "ilvC6E6" is the catalog's `ilvc6e6_ecoli` is curation."""
    resolution = resolve_roles(["ilvC"], parts)
    kari = next(r for r in resolution.roles if r.role == "KARI")
    assert len(kari.part_ids) == 4
    assert kari.ambiguous
    assert resolution.ambiguous_roles == ("KARI",)


def test_a_role_name_is_not_an_enzyme_identification(parts: tuple) -> None:
    """The loosest available reading, and the one that would return 100% recall on empty records:
    treat 'KDC' as 'any KDC part'. It is kept apart from an unrecognised name because the two mean
    different things — a curation limit against a catalog gap — and lead to different verdicts."""
    resolution = resolve_roles(["KDC", "ADH"], parts)
    assert not any(role.filled for role in resolution.roles)
    assert set(resolution.role_named_only) == {"KDC", "ADH"}
    assert resolution.unrecognised == ()


def test_a_gene_family_named_as_a_block_is_a_curation_limit_not_a_catalog_gap(
    parts: tuple,
) -> None:
    """'ILV genes' is verbatim in this atlas's extractions and is the same kind of thing as 'KDC':
    the paper named the steps, not the proteins. Filing it as a catalog gap would put a
    non-existent part called "ILV genes" on the curation worklist, and the worklist is only worth
    reading if every line on it is actionable.

    The family name is a NAMED entry, not a prefix rule: ILV2 must still resolve to a part."""
    vague = resolve_roles(["ILV genes"], parts)
    assert vague.role_named_only == ("ILV genes",)
    assert vague.unrecognised == ()

    specific = resolve_roles(["ILV2"], parts)
    assert specific.role_named_only == ()
    assert dict((r.role, r.part_ids) for r in specific.roles)["AHAS"] == ("ilv2_ilv6_native",)


def test_a_cofactor_cycle_gene_is_recognised_but_fills_no_step_role(parts: tuple) -> None:
    """POS5 and ADH3 are in the catalog as `cofactor_cycle`, not as one of the five steps. Naming
    one is not a catalog gap — the atlas knows the gene — but it does not fill a route step."""
    resolution = resolve_roles(["POS5"], parts)
    assert "pos5" in gene_index(parts)
    assert resolution.unrecognised == ()
    assert resolution.unfilled_roles == STEP_ORDER


# ------------------------------------------------------------------------- matching and misses


def test_a_fully_named_yeast_build_matches_and_names_its_route(parts: tuple, routes: list) -> None:
    verdict = _verdict(_configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH6"]), parts, routes)
    assert verdict.outcome == "matched"
    assert verdict.route_ids
    matched = routes[[r.id for r in routes].index(verdict.route_ids[0])]
    assert matched.strategy == "C_mitochondrial_ehrlich"
    assert {step.part.id for step in matched.steps} == {
        "ilv2_ilv6_native",
        "ilv5_native",
        "ilv3_native",
        "aro10_native",
        "adh6_native",
    }


def test_a_build_naming_three_of_five_enzymes_is_not_recall(parts: tuple, routes: list) -> None:
    """THE CENTRAL STRICTNESS TEST. A route is five choices. Agreeing on three of them is not
    re-discovering the build; it is agreeing about three steps and never checking two. It is
    reported as `partial` — a number with its own name — and never as recall."""
    verdict = _verdict(_configuration(["ILV2", "ILV5", "ILV3", "KDC", "ADH"]), parts, routes)
    assert verdict.outcome == "not_evaluable"
    assert verdict.clause == "under_specified"
    assert verdict.partial, "every NAMED step did agree, and that is the figure it belongs to"
    assert "KDC" in verdict.detail and "ADH" in verdict.detail


def test_a_configuration_naming_no_enzyme_at_all_never_matches(parts: tuple, routes: list) -> None:
    """The failure mode a wildcard rule produces: with every role unspecified, all 120 routes of
    the strategy 'agree', and recall reads 100% against a record that said nothing."""
    verdict = _verdict(_configuration(["ILV genes"]), parts, routes)
    assert verdict.outcome != "matched"


def test_an_enzyme_no_part_carries_is_a_named_miss(parts: tuple, routes: list) -> None:
    """The E. coli-in-yeast shape, with yqhD as the ADH. The verdict must name the enzyme, because
    the name IS the curation action: add a part for it."""
    verdict = _verdict(_configuration(["alsS", "ilvC", "ilvD", "kivD", "yqhD"]), parts, routes)
    assert verdict.outcome == "missed"
    assert verdict.clause == "catalog_gap"
    assert "yqhD" in verdict.detail
    assert "ADH" in verdict.detail


def test_an_ecoli_host_is_held_out_rather_than_counted_either_way(
    parts: tuple, routes: list
) -> None:
    """`enumerate_routes` has no host axis: every route it emits is implicitly a yeast route.
    Counting an E. coli build as re-discovered would be a false recall; counting it as missed
    would blame the enumerator for a scope it was never given."""
    verdict = _verdict(
        _configuration(["alsS", "ilvC", "ilvD", "kivD", "adhA"], organism=_ECOLI), parts, routes
    )
    assert verdict.outcome == "not_evaluable"
    assert verdict.clause == "host_outside_enumeration"


def test_a_strategy_outside_the_five_is_held_out_and_named(parts: tuple, routes: list) -> None:
    """Extraction really does emit 'unknown' and 'NA' for compartment_strategy; two of the live
    proposals carry each."""
    for strategy in ("unknown", "NA", None):
        verdict = _verdict(_configuration(["ILV2"], strategy=strategy), parts, routes)
        assert verdict.clause == "strategy_not_enumerable"
        assert repr(strategy) in verdict.detail


# --------------------------------------------------------------------------- the three numbers


def test_an_empty_table_reports_not_measurable_rather_than_zero_or_one(
    parts: tuple, routes: list
) -> None:
    """The state of the atlas today, and the whole point of the deliverable. 0.0 would say the
    enumerator failed; 1.0 would say it succeeded. Neither is known, and None is the same answer
    `score_evidence` gives for the same reason."""
    report = recall_report((), parts, routes, chassis_organism_id=_YEAST)
    assert report.recall is None
    assert report.coverage is None
    body = "\n".join(describe_report(report))
    assert "CANNOT BE" in body and "EVALUATED" in body


def test_recall_is_over_the_judgeable_set_and_coverage_says_how_big_that_was(
    parts: tuple, routes: list
) -> None:
    """Three numbers, never one. Holding a record out of the denominator is legitimate — it is
    also the easiest way to inflate a figure, so `coverage` reports exactly how much was held."""
    configurations = (
        _configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH6"], name="matched"),
        _configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH2"], name="catalog gap"),
        _configuration(["ILV2", "ILV5", "ILV3", "KDC", "ADH"], name="under specified"),
        _configuration(["ILV2"], strategy="unknown", name="no strategy"),
    )
    report = recall_report(configurations, parts, routes, chassis_organism_id=_YEAST)
    assert report.evaluable == 2
    assert report.recall == pytest.approx(0.5)
    assert report.coverage == pytest.approx(0.5)
    # partial is over ALL four: the matched one and the under-specified one whose named steps agreed
    assert report.partial == pytest.approx(0.5)
    assert report.partial >= report.recall * report.coverage


def test_the_report_names_every_miss_and_the_enzymes_behind_it(parts: tuple, routes: list) -> None:
    """'report recall as a fraction with the misses named' — the fraction alone is not the
    deliverable, and the unrecognised-enzyme list is the curation worklist the harness is for."""
    configurations = (
        _configuration(["ILV2", "ILV5", "ILV3", "ARO10", "ADH2"], name="gap-a"),
        _configuration(["alsS", "ilvC", "ilvD", "kivD", "yqhD"], name="gap-b"),
    )
    report = recall_report(configurations, parts, routes, chassis_organism_id=_YEAST)
    assert report.unrecognised_enzymes == ("ADH2", "yqhD")
    body = "\n".join(describe_report(report))
    assert "MISSED" in body
    assert "gap-a" in body and "gap-b" in body
    assert "ADH2" in body and "yqhD" in body


# -------------------------------------------------------------------------------- the loader


def _db_with(rows: list[tuple[str, str | None, str | None, str]]) -> sqlite3.Connection:
    conn = open_db(IN_MEMORY)
    conn.execute(
        "INSERT INTO organism (id, name, rank, zone, evidence, confidence) "
        "VALUES (?, 'test organism', 'species', 'R', 'synthetic test fixture', 'low')",
        (_YEAST,),
    )
    conn.execute(
        "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, confidence) "
        "VALUES ('YAA:STRAIN:t', ?, 'T', 'engineered', 'R', 'synthetic test fixture', 'low')",
        (_YEAST,),
    )
    for row_id, strategy, host, description in rows:
        conn.execute(
            "INSERT INTO pathway_configuration (id, name, compartment_strategy_id, "
            "host_strain_id, description, zone, evidence, confidence) "
            "VALUES (?, ?, ?, ?, ?, 'R', 'synthetic test fixture', 'low')",
            (row_id, row_id, strategy, host, description),
        )
    return conn


def test_the_loader_resolves_the_host_organism_and_keeps_a_hostless_row(
    parts: tuple, routes: list
) -> None:
    """LEFT JOINs: a configuration with no host is a record to report on, not one to drop. A
    silent INNER JOIN here would improve every figure by deleting the awkward rows."""
    conn = _db_with(
        [
            ("cfg-with-host", "A_native_split", "YAA:STRAIN:t", "enzymes as reported: ILV2"),
            ("cfg-no-host", "A_native_split", None, "enzymes as reported: ILV2"),
        ]
    )
    try:
        configurations = load_configurations(conn)
    finally:
        conn.close()
    assert len(configurations) == 2
    by_id = {c.id: c for c in configurations}
    assert by_id["cfg-with-host"].host_organism_id == _YEAST
    assert by_id["cfg-no-host"].host_organism_id is None
    report = recall_report(configurations, parts, routes, chassis_organism_id=_YEAST)
    assert {v.clause for v in report.verdicts} == {"under_specified", "host_not_recorded"}


def test_an_atlas_with_no_configurations_loads_none_rather_than_erroring(
    parts: tuple, routes: list
) -> None:
    """The state phase 3 sat in for its whole life: 600 routes and nothing to score them against.

    An empty table must come back as an empty tuple and a `recall` of None, not as an exception
    and not as a figure. `describe_report` then says the clause cannot be evaluated in words,
    because a reader of a 0/0 table will otherwise supply their own interpretation of it.
    """
    conn = open_db(IN_MEMORY)
    try:
        configurations = load_configurations(conn)
    finally:
        conn.close()
    assert configurations == ()
    report = recall_report(configurations, parts, routes, chassis_organism_id=_YEAST)
    assert report.recall is None
    assert "CANNOT BE" in "\n".join(describe_report(report))
