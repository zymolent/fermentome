"""Tests for `fermdb.metabolic.curated`.

The balance checks are the point. Curating by hand means mistyping by hand, and an unbalanced
reaction does not look wrong downstream — a route enumerator will happily build a route on it and
score the route perfectly well. So the tests below are mostly about what must be *refused*.

The real curated files are checked too, because they are the ones that matter and they are cheap
to verify: sixteen reactions, three invariants each.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fermdb.config import Settings
from fermdb.db import IN_MEMORY, open_db
from fermdb.metabolic import curated as C

REPO_ROOT = Path(__file__).resolve().parents[1]
PATHS_FILE = REPO_ROOT / "env" / "paths.yaml"


def _met(id_: str, carbons: int, **kwargs: object) -> C.Metabolite:
    return C.Metabolite(id=id_, name=id_, carbons=carbons, **kwargs)  # type: ignore[arg-type]


POOL = {
    "pyruvate": _met("pyruvate", 3),
    "acetaldehyde": _met("acetaldehyde", 2),
    "co2": _met("co2", 1),
    "ethanol": _met("ethanol", 2),
    "nadh": _met("nadh", 0, carrier=True, redox="reduced", pair="nad"),
    "nad_plus": _met("nad_plus", 0, carrier=True, redox="oxidized", pair="nad"),
    "nadph": _met("nadph", 0, carrier=True, redox="reduced", pair="nadp"),
    "nadp_plus": _met("nadp_plus", 0, carrier=True, redox="oxidized", pair="nadp"),
    "atp": _met("atp", 0, carrier=True, adenylate="charged"),
    "adp": _met("adp", 0, carrier=True, adenylate="discharged"),
}


def _reaction(*participants: tuple[str, str, float], **kwargs: object) -> C.Reaction:
    defaults: dict[str, object] = {
        "id": "r",
        "name": "r",
        "step_role": "KDC",
        "compartment": "cytosol",
        "genes": (),
        "equation": "e",
        "reversible": False,
        "evidence": "test",
        "confidence": "high",
    }
    defaults.update(kwargs)
    return C.Reaction(
        participants=tuple(
            C.Participant(metabolite=m, role=r, coefficient=c) for m, r, c in participants
        ),
        **defaults,  # type: ignore[arg-type]
    )


# ------------------------------------------------------------------------------------- carbon


def test_a_balanced_reaction_reports_no_problems() -> None:
    reaction = _reaction(
        ("pyruvate", "substrate", 1), ("acetaldehyde", "product", 1), ("co2", "product", 1)
    )
    assert C.check_balance(reaction, POOL) == []


def test_a_lost_carbon_is_caught() -> None:
    """Forgetting the CO2 on a decarboxylation: three carbons in, two out."""
    reaction = _reaction(("pyruvate", "substrate", 1), ("acetaldehyde", "product", 1))
    problems = C.check_balance(reaction, POOL)
    assert any("carbon: 3 in, 2 out" in p for p in problems)


def test_a_coefficient_typo_is_caught() -> None:
    """The acetolactate synthase shape: it takes *two* pyruvate, and one is a plausible typo."""
    reaction = _reaction(
        ("pyruvate", "substrate", 1), ("acetaldehyde", "product", 2), ("co2", "product", 1)
    )
    assert any("carbon" in p for p in C.check_balance(reaction, POOL))


def test_an_undeclared_metabolite_is_refused_rather_than_skipped() -> None:
    """Skipping it would let the reaction balance by ignoring the participant that unbalances it."""
    reaction = _reaction(("pyruvate", "substrate", 1), ("mystery", "product", 1))
    with pytest.raises(C.PathwayError, match="not declared"):
        C.check_balance(reaction, POOL)


# -------------------------------------------------------------------------------------- redox


def test_a_dangling_reduced_cofactor_is_caught() -> None:
    """NADH consumed but no NAD+ produced."""
    reaction = _reaction(
        ("acetaldehyde", "substrate", 1),
        ("nadh", "substrate", 1),
        ("ethanol", "product", 1),
    )
    problems = C.check_balance(reaction, POOL)
    assert any("carrier" in p or "nad redox" in p for p in problems)


def test_a_silently_swapped_pool_is_caught() -> None:
    """NADH in, NADP+ out. The NADPH/NADH mismatch across Ilv5 and the alcohol dehydrogenase is
    the whole reason the DUET architecture exists, so a typo that quietly crossed the pools would
    erase the problem this atlas is for."""
    reaction = _reaction(
        ("acetaldehyde", "substrate", 1),
        ("nadh", "substrate", 1),
        ("ethanol", "product", 1),
        ("nadp_plus", "product", 1),
    )
    problems = C.check_balance(reaction, POOL)
    assert any("redox" in p for p in problems)


def test_a_declared_pool_transfer_is_allowed_but_still_conserves_carriers() -> None:
    """Pos5 phosphorylates NADH to NADPH: the molecule changes pool, its redox state does not, so
    neither NAD+ nor NADP+ appears. It must be declared, never inferred."""
    pos5 = _reaction(
        ("nadh", "substrate", 1),
        ("atp", "substrate", 1),
        ("nadph", "product", 1),
        ("adp", "product", 1),
        transfers_redox_pool=True,
    )
    assert C.check_balance(pos5, POOL) == []

    undeclared = _reaction(
        ("nadh", "substrate", 1),
        ("atp", "substrate", 1),
        ("nadph", "product", 1),
        ("adp", "product", 1),
    )
    assert C.check_balance(undeclared, POOL), "an undeclared pool transfer must not pass silently"


def test_a_pool_transfer_that_loses_a_carrier_is_still_caught() -> None:
    """The relaxation is per-pool only; a dinucleotide that goes in still has to come out."""
    reaction = _reaction(
        ("nadh", "substrate", 1),
        ("atp", "substrate", 1),
        ("adp", "product", 1),
        transfers_redox_pool=True,
    )
    assert any("carrier" in p for p in C.check_balance(reaction, POOL))


# ---------------------------------------------------------------------------------- adenylate


def test_atp_without_adp_is_caught() -> None:
    reaction = _reaction(
        ("nadh", "substrate", 1),
        ("atp", "substrate", 1),
        ("nadph", "product", 1),
        transfers_redox_pool=True,
    )
    assert any("adenylate" in p for p in C.check_balance(reaction, POOL))


# --------------------------------------------------------------- the real files, really checked


def _settings() -> Settings:
    return Settings.load(paths_file=PATHS_FILE, env={})


def test_both_curated_pathways_load_and_every_reaction_balances() -> None:
    """If this fails, load_pathway_file raises and names the reaction and the invariant."""
    pathways = C.load_pathways(_settings())
    assert {p.id for p in pathways} == {"isobutanol_valine_ehrlich", "ethanol_reference"}
    assert sum(len(p.reactions) for p in pathways) == 16


def test_the_isobutanol_route_keeps_its_compartment_boundary() -> None:
    """The engineering problem is that 2-KIV is made in the matrix and decarboxylated in the
    cytosol. If both steps ever end up in one compartment the route has been flattened and the
    thing the atlas exists to reason about has gone."""
    pathways = {p.id: p for p in C.load_pathways(_settings())}
    route = pathways["isobutanol_valine_ehrlich"]
    by_role = {r.step_role: r for r in route.reactions if not r.competing}
    assert by_role["DHAD"].compartment == "mitochondrial_matrix"
    assert by_role["KDC"].compartment == "cytosol"


def test_the_three_drains_on_the_precursor_pool_are_all_present() -> None:
    """PLAN.md G.3's 2026-09-20 amendment: the competing set was incomplete without ECM31, and
    incomplete is not the same as abbreviated — a route ranker enumerating deletion candidates
    would simply not have seen it."""
    pathways = {p.id: p for p in C.load_pathways(_settings())}
    competing = [r for r in pathways["isobutanol_valine_ehrlich"].reactions if r.competing]
    genes = {gene for reaction in competing for gene in reaction.genes}
    assert {"BAT1", "BAT2", "LEU4", "LEU9", "ECM31"} <= genes


def test_ecm31_is_marked_unverified() -> None:
    """Its biochemistry is asserted from background knowledge and has never been checked against a
    source. PLAN.md says so explicitly, so the row must not claim otherwise."""
    pathways = {p.id: p for p in C.load_pathways(_settings())}
    ecm31 = next(r for r in pathways["isobutanol_valine_ehrlich"].reactions if "ECM31" in r.genes)
    assert ecm31.confidence == "unverified"


def test_writing_is_idempotent() -> None:
    pathways = C.load_pathways(_settings())
    connection = open_db(IN_MEMORY)
    try:
        first = C.write_pathways(connection, pathways)
        C.write_pathways(connection, pathways)
        assert first["reaction"] == 16
        assert connection.execute("SELECT COUNT(*) FROM reaction").fetchone()[0] == 16
        assert connection.execute("SELECT COUNT(*) FROM pathway").fetchone()[0] == 2
    finally:
        connection.close()


# --------------------------------------------------------------------------------------- parts


def test_the_parts_catalog_covers_every_step_of_the_route() -> None:
    """Route enumeration is {step -> part} x compartment x cofactor x host. A step role with no
    candidate part makes the whole product empty, silently."""
    parts = C.load_parts(_settings())
    covered = {part.step_role for part in parts}
    assert {"AHAS", "KARI", "DHAD", "KDC", "ADH"} <= covered


def test_the_cofactor_switched_kari_is_marked_as_such() -> None:
    """An NADH-preferring KARI is a different route, not a different allele: it removes the
    requirement for matrix NADPH and with it the Pos5 dependency the expression baseline shows is
    the thinnest link in strategy C. The ranker has to be able to see that."""
    parts = {part.id: part for part in C.load_parts(_settings())}
    switched = parts["ilvc_nadh_variant"]
    assert switched.engineered_switch is True
    assert switched.cofactor_preference == "NADH"
    assert switched.variant_of == "ilvc_ecoli"
    assert parts["ilvc_ecoli"].cofactor_preference == "NADPH"


def test_the_iron_sulfur_steps_are_flagged_oxygen_sensitive() -> None:
    """Both DHAD enzymes carry [4Fe-4S]. Relocalizing one to the cytosol makes the route depend on
    cytosolic cluster assembly, which is a scored risk rather than a footnote."""
    dhad = [p for p in C.load_parts(_settings()) if p.step_role == "DHAD"]
    assert dhad and all(p.oxygen_sensitivity == "sensitive" for p in dhad)


def test_every_part_declares_the_genome_its_sequence_would_be_carried_on() -> None:
    """The one thing this project has been wrong about before. A part's encoding genome decides
    which NCBI translation table its sequence reads under, and it is never inferred from the
    compartment the enzyme works in -- Adh3 works in the matrix and is nuclear-encoded."""
    for part in C.load_parts(_settings()):
        assert part.sequence_encoding_genome in {"nuclear", "mitochondrial"}


def test_the_whole_catalog_is_zone_i() -> None:
    """`write_parts` stamps zone 'I' on every row, whatever the entry's own confidence says.

    The zone is a property of the loader, not of the claim, so it stays uniform even now that one
    entry was read from a source rather than recalled.
    """
    connection = open_db(IN_MEMORY)
    try:
        C.write_parts(connection, C.load_parts(_settings()))
        zones = {row[0] for row in connection.execute("SELECT DISTINCT zone FROM part")}
        assert zones == {"I"}
    finally:
        connection.close()


def test_only_the_entries_that_cite_a_source_are_better_than_unverified() -> None:
    """A catalog that files a checked claim beside an unchecked one at the same confidence has
    thrown away the distinction confidence exists to record.

    The default is `unverified` and the file's header says why: almost everything in it is
    background knowledge. `adh7_native` is the exception -- written by reading the stored full text
    of 10.1016/j.cels.2019.10.006 and quoting it -- so it carries `medium`, and its evidence has to
    name the source that earns it. `high` is not available to this file at all: one paper's report
    of its own construction, unconfirmed by anything else, is not a verified fact.
    """
    for part in C.load_parts(_settings()):
        assert part.confidence in {"unverified", "medium"}, part.id
        if part.confidence != "unverified":
            assert "10.1016/j.cels.2019.10.006" in part.evidence, part.id


def test_a_field_the_source_does_not_support_is_left_unknown() -> None:
    """The obligation that comes with citing a source: the citation must not leak into the fields
    the source is silent about.

    10.1016/j.cels.2019.10.006 says which step Adh7 runs and where, and says nothing at all about
    which cofactor it uses. 'NADPH' from background knowledge would look exactly as trustworthy as
    the quoted fields beside it. 'unknown' is also the value the enumerator handles correctly: it
    is skipped by both the cofactor gate and the per-compartment demand tally, so the part cannot
    contribute a redox demand nobody has checked.
    """
    adh7 = {p.id: p for p in C.load_parts(_settings())}["adh7_native"]
    assert adh7.cofactor_preference == "unknown"
    assert adh7.oxygen_sensitivity == "unknown"
