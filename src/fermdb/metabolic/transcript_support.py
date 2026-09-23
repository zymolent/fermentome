"""Whether a route's steps are backed by transcript data, step by step.

`pathway_route.score_evidence` has been NULL on every route since enumeration began, and the
route listing says so in as many words: *"Evidence and toxicity are NULL on every route: nothing
has been extracted from the literature and no tolerance has been measured."* This module fills
one half of that -- the transcript half -- and it fills it without letting expression pretend to
be flux.

## What "backed by transcript data" is allowed to mean here

A route is a set of (step role, part, compartment) triples. A transcriptome measures **transcript
abundance of genes in one strain under one condition**. Four things follow, and each is enforced
rather than merely noted:

1. **Only a built strain can supply evidence.** A route is matched to a strain whose *declared
   construct* has the same compartment topology and the same KARI cofactor preference. Nothing is
   transferred between topologies: a cytosolic build says nothing about whether the mitochondrial
   version of the same step is expressed, because the construct, the promoter and the import step
   all differ.
2. **Only a gene present in the quantified transcriptome can be measured.** A heterologous part
   (`alsS`, `kivd`, `adhA`, `ilvC`) quantified against an S288C-only index has no reference to map
   to, and its reads sit in the unmapped fraction. That is reported as ``not_measurable``, which
   is distinct from ``unchanged`` -- the first says the instrument could not see it, the second
   says it looked and found nothing. Conflating them would let an unmeasured step look verified.
3. **Expression is not flux, and elevated is not sufficient.** A step whose gene is elevated in a
   producer is evidence that the construct is transcribed. It is not evidence that the enzyme is
   folded, imported, active, or carrying flux. The verdicts are named accordingly
   (``elevated_in_build``, not ``working``), and :func:`describe` prints the caveat beside the
   score rather than in a footnote.
4. **A step with no contrast is not a step that failed.** It scores nothing and is reported as
   ``no_contrast``, so a route in a topology nobody has built is visibly unevidenced rather than
   penalised as though it had been tried.

## The score

``score_evidence`` becomes the fraction of a route's catalytic steps that are *measurable and
measured* in a matching build -- not the fraction that are elevated. A step measured and found
unchanged is evidence; it is the finding that the declared construct did not raise its transcript,
which is exactly what a route ranking should be able to see. What the score refuses to reward is
absence.
"""

from __future__ import annotations

import gzip
import json
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ..paths import resolve_stored_path

__all__ = [
    "RouteSupport",
    "StepSupport",
    "StrainConstruct",
    "contrast_tables",
    "describe",
    "route_support",
    "strain_constructs",
    "write_scores",
]

#: Catalytic roles. `cofactor_cycle` is excluded from the score's denominator because it is an
#: optional supporting step rather than a step the pathway must have -- counting it would make a
#: route look less evidenced for carrying a redox part.
CATALYTIC_ROLES: Final[frozenset[str]] = frozenset({"AHAS", "KARI", "DHAD", "KDC", "ADH"})

#: Fold-change and significance thresholds for calling a step elevated. Both must be met. The
#: fold-change floor exists because with n=3 a small but significant change is not evidence that
#: a construct is doing anything: a promoter swap that moves a transcript by 20% is
#: indistinguishable from growth-rate drift between two strains.
#: How a construct-copy measurement is keyed, so it can never be mistaken for the native gene.
CASSETTE_SUFFIX: Final[str] = "@cassette"

MIN_LOG2FC: Final[float] = 1.0
MAX_P_ADJUSTED: Final[float] = 0.05


@dataclass(frozen=True, slots=True)
class StrainConstruct:
    """A built strain's declared construct, as `omics.run_conditions` parsed it."""

    strain_id: str
    name: str
    #: gene symbol -> compartment
    localization: Mapping[str, str]
    parent_as_declared: str
    raw: str

    @property
    def topology(self) -> frozenset[str]:
        return frozenset(self.localization.values())

    @property
    def encoding_genome(self) -> str:
        """Where the construct is *encoded*, which is not where its product works.

        Every build in this corpus is nuclear-encoded, including the mitochondrially targeted one:
        a CoxIV presequence sends a protein to the matrix, and the gene stays in the nucleus and
        is translated on cytosolic ribosomes under table 1. The README calls conflating this with
        mtDNA encoding "the most expensive modelling error available here", and the cost of the
        conflation is precise: it would let a strategy-E route, which requires editing the
        mitochondrial genome and has no published isobutanol precedent, inherit the transcript
        evidence of a routine presequence fusion.

        A construct is mitochondrially encoded only if the declaration says it was integrated into
        mtDNA. Nothing in this corpus does, so this returns ``'nuclear'`` for every parsed
        construct -- and it is a method rather than a constant so that the day something does, the
        parse and not an assumption decides.
        """
        declaration = self.raw.lower()
        mtdna_markers = ("mtdna", "mitochondrial genome", "rho0", "rho-zero", "biolistic", "cox2::")
        return "mitochondrial" if any(m in declaration for m in mtdna_markers) else "nuclear"

    def kari_cofactor(self) -> str:
        """NADH when the build carries a bacterial KARI, NADPH when it carries the yeast one.

        Read from which KARI gene the construct names, never from the strain's label.
        """
        if "ilvC" in self.localization:
            return "NADH"
        if "ILV5" in self.localization:
            return "NADPH"
        return "unknown"


@dataclass(frozen=True, slots=True)
class StepSupport:
    step_order: int
    role: str
    part_id: str
    compartment: str
    genes: tuple[str, ...]
    source_organism: str
    status: str
    log2_fold_change: float | None = None
    p_adjusted: float | None = None
    contrast_id: str | None = None
    strain: str | None = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class RouteSupport:
    route_id: str
    strategy: str
    steps: tuple[StepSupport, ...]
    matched_strains: tuple[str, ...]
    score: float | None
    caveats: tuple[str, ...] = field(default_factory=tuple)

    @property
    def measured(self) -> int:
        return sum(
            1
            for s in self.steps
            if s.status
            in {
                "elevated_in_build",
                "elevated_not_resolved",
                "unchanged_in_build",
                "reduced_in_build",
                "inconsistent_across_contrasts",
            }
        )

    @property
    def elevated(self) -> int:
        return sum(1 for s in self.steps if s.status == "elevated_in_build")


# ------------------------------------------------------------------------------------ the inputs


def strain_constructs(conn: sqlite3.Connection) -> dict[str, StrainConstruct]:
    """Every strain whose genotype carries a parsed construct, keyed by strain id."""
    out: dict[str, StrainConstruct] = {}
    for strain_id, name, as_reported, parsed in conn.execute(
        "SELECT g.strain_id, s.canonical_name, g.as_reported, g.parsed_json "
        "FROM genotype g JOIN strain s ON s.id = g.strain_id "
        "WHERE g.parsed_json IS NOT NULL"
    ):
        try:
            payload = json.loads(str(parsed))
        except (TypeError, ValueError):
            continue
        localization = {
            gene: str(entry.get("compartment", "unknown"))
            for gene, entry in (payload.get("localization") or {}).items()
        }
        if not localization:
            continue
        out[str(strain_id)] = StrainConstruct(
            strain_id=str(strain_id),
            name=str(name),
            localization=localization,
            parent_as_declared=str(payload.get("parent_as_declared", "")),
            raw=str(as_reported),
        )
    return out


def contrast_tables(
    conn: sqlite3.Connection,
    *,
    symbols: Mapping[str, str],
    data_dir: Path,
    cassette: Mapping[str, str] | None = None,
) -> dict[str, dict[str, tuple[float, float | None]]]:
    """Stored genotype contrasts -> {contrast id: {gene symbol: (log2FC, p_adjusted)}}.

    Only contrasts whose payload is still on disk are read; a missing payload is skipped rather
    than treated as an empty result, because "the file is gone" and "the gene did not change" are
    different and only one of them is a finding.

    `data_dir` is required rather than optional because of how that skip fails. `payload_ref`
    holds whatever path the machine that computed the contrast wrote, and on any *other* machine
    an absolute one names nothing — so every contrast would be skipped, and this function would
    return `{}` without raising. The caller then reports zero transcript-backed routes, which
    reads as a finding rather than as a path bug. `resolve_stored_path` re-anchors the recorded
    path against this machine's derived tier, and needs that tier named.
    """
    tables: dict[str, dict[str, tuple[float, float | None]]] = {}
    by_systematic = {systematic: symbol for systematic, symbol in symbols.items()}
    # A cassette row is filed under `SYMBOL@cassette`, never under the bare symbol. Sharing the
    # key would let the construct's copy stand in for the native gene, which is the confusion
    # this whole distinction exists to prevent -- in the opposite direction.
    for symbol, row in (cassette or {}).items():
        by_systematic[row] = f"{symbol}{CASSETTE_SUFFIX}"
    for analysis_id, payload_ref in conn.execute(
        "SELECT id, payload_ref FROM analysis_result WHERE kind = 'differential_expression'"
    ):
        path = resolve_stored_path(str(payload_ref).split(" (")[0], data_dir=data_dir)
        if not path.is_file():
            continue
        table: dict[str, tuple[float, float | None]] = {}
        with gzip.open(path, "rt") as handle:
            header = handle.readline().rstrip("\n").split("\t")
            index = {name: i for i, name in enumerate(header)}
            for line in handle:
                fields = line.rstrip("\n").split("\t")
                resolved = by_systematic.get(fields[0])
                if resolved is None:
                    continue
                raw_p = fields[index["p_adjusted"]]
                table[resolved] = (
                    float(fields[index["log2_fold_change"]]),
                    float(raw_p) if raw_p else None,
                )
        tables[str(analysis_id)] = table
    return tables


# ------------------------------------------------------------------------------------ the verdict


def _status(
    genes: Sequence[str],
    source_organism: str,
    tables: Sequence[tuple[str, Mapping[str, tuple[float, float | None]]]],
    measurable_genes: frozenset[str],
    construct_genes: frozenset[str] = frozenset(),
    reference_includes_constructs: bool = False,
) -> tuple[str, float | None, float | None, str, str | None]:
    """A step's verdict across **every** matching contrast, not one picked arbitrarily.

    The three timepoints of a producer series are three independent measurements of the same
    construct, and which one a reader happens to get should not decide what the atlas says. So
    each gene is read from all of them and the verdict requires agreement:

    * ``elevated_in_build`` -- at least one contrast passes both thresholds, and **no** contrast
      passes them in the opposite direction. A construct that is up at 4 h and down at 26 h is
      reported as ``inconsistent``, because that is what it is.
    * ``unchanged_in_build`` -- measured everywhere it was looked for, and nowhere distinguishable
      from the parent.

    Reporting the strongest of several contrasts without this check is how a single contaminated
    replicate group, or a single lucky timepoint, becomes a claim.
    """
    yeast = source_organism.strip().lower().startswith("saccharomyces")
    if not yeast:
        return (
            "not_measurable",
            None,
            None,
            f"{source_organism} gene(s) {', '.join(genes)}: no reference in the quantified "
            "transcriptome, so their reads are in the unmapped fraction and their expression is "
            "unmeasured, not zero",
            None,
        )
    present = [g for g in genes if g in measurable_genes]
    if not present:
        return (
            "not_measurable",
            None,
            None,
            f"{', '.join(genes)} is not a row in the expression matrix",
            None,
        )
    if not tables:
        return (
            "no_contrast",
            None,
            None,
            "no producer-vs-parent contrast in this topology and encoding genome",
            None,
        )

    # The confound that cost this module its first published verdict. When the build's cassette
    # carries its own copy of a gene and the quantification reference contains only the native
    # genome, the native gene's row is not a measurement of the native gene: it is the native
    # gene plus however many cassette reads the aligner mis-assigned to it. Codon optimization
    # reduces that leak but does not reliably abolish it -- a retained exact substring as short
    # as the aligner's seed length is enough. In the study this was first run against, the
    # synthetic ILV3 kept a 44 nt exact match against a k=31 index and leaked an estimated 12%
    # of cassette reads onto native ILV3, which reads as a 30-fold "overexpression" that is
    # entirely artefact.
    #
    # The two cases are indistinguishable from the counts alone, so neither is asserted. The
    # step is reported as confounded, which is honest and which the augmented-reference
    # requantification resolves -- at which point `reference_includes_constructs` is True and
    # this branch stops firing.
    # A gene the build carries on its cassette is measured on the CASSETTE row when the index
    # has one. That row shares reads with nothing, so it is the only honest measurement of
    # whether the engineered step is transcribed -- and it is the measurement the question asks
    # for. The native row keeps its own separate meaning: how much of the host's own copy is
    # running, which is a different question and is answered under the bare symbol.
    on_cassette = [g for g in genes if f"{g}{CASSETTE_SUFFIX}" in (tables[0][1] if tables else {})]
    if on_cassette:
        key = f"{on_cassette[0]}{CASSETTE_SUFFIX}"
        cassette_observations = [
            (contrast_id, key, table[key][0], table[key][1])
            for contrast_id, table in tables
            if key in table
        ]
        if cassette_observations:
            passing = [
                o
                for o in cassette_observations
                if o[3] is not None and o[3] <= MAX_P_ADJUSTED and abs(o[2]) >= MIN_LOG2FC
            ]
            total = len({o[0] for o in cassette_observations})
            if passing and all(o[2] > 0 for o in passing):
                contrast_id, _k, lfc, padj = max(passing, key=lambda o: abs(o[2]))
                return (
                    "elevated_in_build",
                    lfc,
                    padj,
                    f"the construct's own {on_cassette[0]} copy is {lfc:+.2f} log2 over the "
                    f"parent, FDR {padj:.3g} ({len({o[0] for o in passing})} of {total} "
                    "matching contrast(s) agree) -- measured on the cassette row, which shares "
                    "reads with nothing",
                    contrast_id,
                )
            contrast_id, _k, lfc, padj = max(cassette_observations, key=lambda o: abs(o[2]))
            if abs(lfc) >= MIN_LOG2FC:
                # Measured, large, and not resolvable by this test. Calling a 12 log2 difference
                # "unchanged" because a Welch t at n=3 could not clear BH over 5,800 genes would
                # be the same error the contrast layer already refuses to make: a null at this
                # replication is uninformative, never a finding of no effect.
                return (
                    "elevated_not_resolved",
                    lfc,
                    padj,
                    f"the construct's own {on_cassette[0]} copy sits {lfc:+.2f} log2 above the "
                    f"parent across {total} matching contrast(s), but no contrast resolves it at "
                    f"FDR {MAX_P_ADJUSTED}. At this replication that is underpowered, not "
                    "negative -- the fold change is the evidence and the test is not",
                    contrast_id,
                )
            return (
                "unchanged_in_build",
                lfc,
                padj,
                f"the construct's own {on_cassette[0]} copy differs from the parent by at most "
                f"{lfc:+.2f} log2 across {total} matching contrast(s)",
                contrast_id,
            )

    confounded = [g for g in present if g in construct_genes]
    if confounded and not reference_includes_constructs:
        return (
            "confounded_by_construct",
            None,
            None,
            f"the build's cassette carries its own {', '.join(confounded)}, and this "
            "quantification's reference does not, so reads from the construct can be assigned "
            "to the native locus. The row cannot separate native expression from cassette "
            "spillover; requantify against a construct-augmented index to resolve it",
            None,
        )

    observations: list[tuple[str, str, float, float | None]] = []
    for contrast_id, table in tables:
        for gene in present:
            entry = table.get(gene)
            if entry is not None:
                observations.append((contrast_id, gene, entry[0], entry[1]))
    if not observations:
        return (
            "no_contrast",
            None,
            None,
            f"{', '.join(present)} not tested in any matching contrast",
            None,
        )

    def passes(lfc: float, padj: float | None) -> bool:
        return padj is not None and padj <= MAX_P_ADJUSTED and abs(lfc) >= MIN_LOG2FC

    up = [o for o in observations if passes(o[2], o[3]) and o[2] > 0]
    down = [o for o in observations if passes(o[2], o[3]) and o[2] < 0]
    total = len({o[0] for o in observations})

    if up and down:
        return (
            "inconsistent_across_contrasts",
            None,
            None,
            f"{present[0]} is significantly up in {len({o[0] for o in up})} and down in "
            f"{len({o[0] for o in down})} of {total} matching contrast(s); the atlas reports the "
            "disagreement rather than choosing one",
            None,
        )
    winners = up or down
    if winners:
        contrast_id, gene, lfc, padj = max(winners, key=lambda o: abs(o[2]))
        return (
            "elevated_in_build" if lfc > 0 else "reduced_in_build",
            lfc,
            padj,
            f"{gene} {lfc:+.2f} log2, FDR {padj:.3g} "
            f"({len({o[0] for o in winners})} of {total} matching contrast(s) agree)",
            contrast_id,
        )
    contrast_id, gene, lfc, padj = max(observations, key=lambda o: abs(o[2]))
    if abs(lfc) >= MIN_LOG2FC:
        return (
            "elevated_not_resolved",
            lfc,
            padj,
            f"{gene} sits {lfc:+.2f} log2 from the parent across {total} matching contrast(s) "
            f"but no contrast resolves it at FDR {MAX_P_ADJUSTED}; underpowered, not negative",
            contrast_id,
        )
    return (
        "unchanged_in_build",
        lfc,
        padj,
        f"{gene} largest change {lfc:+.2f} log2"
        + (f", FDR {padj:.3g}" if padj is not None else ", not tested")
        + f" across {total} matching contrast(s) -- measured, never distinguishable from parent",
        contrast_id,
    )


def route_support(
    conn: sqlite3.Connection,
    route_id: str,
    *,
    parts: Mapping[str, tuple[tuple[str, ...], str]],
    constructs: Mapping[str, StrainConstruct],
    contrasts: Mapping[str, dict[str, tuple[float, float | None]]],
    contrast_strains: Mapping[str, tuple[str, str]],
    measurable_genes: frozenset[str],
    reference_includes_constructs: bool = False,
) -> RouteSupport:
    """One route's transcript support.

    ``contrast_strains`` maps a contrast id to ``(reference strain id, treatment strain id)``;
    only a contrast whose *treatment* side is a build matching this route's topology is used, and
    whose reference side is that build's declared parent.
    """
    steps = list(
        conn.execute(
            "SELECT step_order, step_role_id, part_id, compartment_id, encoding_genome "
            "FROM pathway_route_step WHERE route_id = ? ORDER BY step_order",
            (route_id,),
        )
    )
    strategy = str(
        conn.execute(
            "SELECT cofactor_strategy FROM pathway_route WHERE id = ?", (route_id,)
        ).fetchone()[0]
    )

    catalytic = [s for s in steps if str(s[1]) in CATALYTIC_ROLES]
    route_topology = frozenset(str(s[3]) for s in catalytic)
    kari_part = next((str(s[2]) for s in catalytic if str(s[1]) == "KARI"), "")
    route_kari = (
        "NADH"
        if "nadh" in kari_part or "6e6" in kari_part or "p2d1a1" in kari_part
        else ("NADPH" if kari_part else "unknown")
    )

    # The route's encoding genome, read from the steps rather than from the strategy label.
    route_encoding = {str(s[4]) for s in catalytic}

    matched = [
        construct
        for construct in constructs.values()
        if construct.topology == route_topology
        and construct.kari_cofactor() in {route_kari, "unknown"}
        # A presequence-targeted nuclear gene is not an mtDNA-encoded one. Without this clause a
        # strategy-E route inherits Y797's evidence, and strategy E is the one with no published
        # isobutanol precedent and a genome-editing requirement behind it.
        and route_encoding <= {construct.encoding_genome}
    ]
    matched_ids = {c.strain_id for c in matched}

    # Only a build-versus-its-own-parent contrast is evidence that a construct is expressed.
    # A producer-versus-producer contrast holds the pathway roughly constant and measures the
    # difference between two designs; reading it as "expressed" would let a step count as
    # transcript-backed because the *other* strain expressed it less.
    by_name = {c.strain_id: c for c in constructs.values()}
    names = {
        strain_id: str(name)
        for strain_id, name in conn.execute("SELECT id, canonical_name FROM strain")
    }
    usable = []
    for contrast_id, table in sorted(contrasts.items()):
        reference_id, treatment_id = contrast_strains.get(contrast_id, ("", ""))
        if treatment_id not in matched_ids:
            continue
        build = by_name.get(treatment_id)
        parent = (build.parent_as_declared if build else "").strip()
        if not parent or names.get(reference_id, "") != parent:
            continue
        usable.append((contrast_id, table))

    # Every gene the matched builds carry on their cassettes. Read from the parsed constructs,
    # so adding a build with a different cassette changes what is treated as confounded.
    cassette_genes = frozenset(gene for construct in matched for gene in construct.localization)

    supports: list[StepSupport] = []
    for step_order, role, part_id, compartment, _encoding in steps:
        genes, organism = parts.get(str(part_id), ((), "unknown"))
        tables = usable if str(role) in CATALYTIC_ROLES else []
        status, lfc, padj, note, used_contrast = _status(
            genes,
            organism,
            tables,
            measurable_genes,
            construct_genes=cassette_genes,
            reference_includes_constructs=reference_includes_constructs,
        )
        supports.append(
            StepSupport(
                step_order=int(step_order),
                role=str(role),
                part_id=str(part_id),
                compartment=str(compartment),
                genes=genes,
                source_organism=organism,
                status=status,
                log2_fold_change=lfc,
                p_adjusted=padj,
                contrast_id=used_contrast,
                strain=(
                    contrast_strains.get(used_contrast, ("", ""))[1] if used_contrast else None
                ),
                note=note,
            )
        )

    catalytic_supports = [s for s in supports if s.role in CATALYTIC_ROLES]
    measured = sum(
        1
        for s in catalytic_supports
        if s.status
        in {
            "elevated_in_build",
            "elevated_not_resolved",
            "unchanged_in_build",
            "reduced_in_build",
            "inconsistent_across_contrasts",
        }
    )
    score = (measured / len(catalytic_supports)) if catalytic_supports else None

    caveats: list[str] = []
    if not matched:
        caveats.append(
            "no built strain in this atlas has this route's compartment topology and KARI "
            "cofactor, so nothing about it has been measured in a transcriptome"
        )
    confounded_steps = [s for s in catalytic_supports if s.status == "confounded_by_construct"]
    if confounded_steps:
        caveats.append(
            f"{len(confounded_steps)} of {len(catalytic_supports)} catalytic steps name a gene "
            "the build also carries on its cassette; against a native-only reference those rows "
            "cannot separate native expression from construct spillover, and are not counted as "
            "measured"
        )
    unmeasurable = [s for s in catalytic_supports if s.status == "not_measurable"]
    if unmeasurable:
        caveats.append(
            f"{len(unmeasurable)} of {len(catalytic_supports)} catalytic steps use heterologous "
            "parts that the S288C quantification cannot see at all"
        )
    if score is not None and score > 0:
        caveats.append(
            "transcript abundance is not flux: an elevated step is a transcribed construct, not "
            "a demonstrated activity, import or carbon flow"
        )
    return RouteSupport(
        route_id=route_id,
        strategy=strategy,
        steps=tuple(supports),
        matched_strains=tuple(sorted(c.name for c in matched)),
        score=score,
        caveats=tuple(caveats),
    )


def write_scores(conn: sqlite3.Connection, supports: Sequence[RouteSupport]) -> int:
    """Write `score_evidence` for each route. NULL stays NULL where nothing was measured."""
    written = 0
    for support in supports:
        if support.score is None:
            continue
        conn.execute(
            "UPDATE pathway_route SET score_evidence = ? WHERE id = ?",
            (support.score, support.route_id),
        )
        written += 1
    return written


def describe(support: RouteSupport) -> str:
    lines = [
        f"route {support.route_id}  strategy={support.strategy}",
        f"  transcript-backed catalytic steps: {support.measured}/"
        f"{sum(1 for s in support.steps if s.role in CATALYTIC_ROLES)}"
        f"  ({support.elevated} elevated in a matching build)",
        f"  matched build(s): {', '.join(support.matched_strains) or 'none'}",
    ]
    for step in support.steps:
        lines.append(
            f"    {step.step_order}. {step.role:14s} {step.compartment:20s} "
            f"{step.status:20s} {step.note}"
        )
    for caveat in support.caveats:
        lines.append(f"  ! {caveat}")
    return "\n".join(lines)
