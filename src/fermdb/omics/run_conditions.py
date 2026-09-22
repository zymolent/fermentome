"""Turn a sequencing run's *declared* metadata into strains, conditions and sample links.

`omics.baseline` could not group 99 runs because nothing in the atlas said what any of them was.
That was true of the database, not of the world: SRA carries a `SAMPLE_ATTRIBUTES` block per run,
and for the studies this corpus cares about the block is unusually complete -- SRP342112 declares
the full construct of every producer strain, down to promoter, terminator and targeting sequence,
and declares the parent it was built from inside the genotype string itself.

This module reads those declarations out of `docs/drafts/omics/*-run-attributes.tsv` and turns
them into rows. The distinction it is built around:

* **Declared** is what the submitter wrote. `genotype = "Y795 with HO::pADH1-ScILV2-tCYC1 ..."`
  is a fact about the deposit, and it becomes a `strain` and a `genotype` row at Zone R with the
  attribute quoted in `evidence`.
* **Parsed** is this module reading structure out of that string -- that `ScILV2` with no `N54`
  suffix is the full-length, MTS-bearing, mitochondrial form while `ScILV2N54` is the truncation
  that puts it in the cytosol. The parse is Zone H, it is recorded separately in
  :class:`Construct`, and every consumer can tell the two apart.
* **Inferred** is anything neither of the above supports, and this module does not do it. A study
  that declares no medium gets a context with no medium facet -- not a default, not a guess. The
  facet is absent, `context_hash` hashes its absence differently from a recorded `unknown`, and
  the atlas's answer will say the medium is unknown wherever it matters.

## Why a timepoint-only context is still a context, and how it avoids colliding

SRP342112 declares `time_point` and nothing else about conditions. A context recording only
`time_h = 26` would hash identically to any other study's hour 26, and two unrelated fermentations
would silently share one row -- the exact merge `curate.contexts` refuses. So the declared
timepoint *label* travels with it as a `sampling_basis` facet ("T14 - hour 26 (SRP342112)"),
which is the submitter's own string plus the study it was declared in. It is not invented, it
disambiguates, and it keeps the honest position that what is known about these conditions is a
clock reading.
"""

from __future__ import annotations

import csv
import json
import re
import sqlite3
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from ..curate.context_writer import ContextWrite
from ..curate.contexts import Facet

__all__ = [
    "Construct",
    "DeclaredRun",
    "StrainDeclaration",
    "context_writes",
    "load_run_attributes",
    "parse_construct",
    "parse_timepoint_hours",
    "strain_declarations",
    "write_strains",
]

#: The pathway genes this atlas tracks, as they appear inside a declared construct string. Keys
#: are the token the submitter writes; values are (gene symbol, source organism).
_CONSTRUCT_GENES: Final[Mapping[str, tuple[str, str]]] = {
    "ScILV2": ("ILV2", "Saccharomyces cerevisiae"),
    "ScILV3": ("ILV3", "Saccharomyces cerevisiae"),
    "ScILV5": ("ILV5", "Saccharomyces cerevisiae"),
    "ScARO10": ("ARO10", "Saccharomyces cerevisiae"),
    "LlAdhA": ("adhA", "Lactococcus lactis"),
    "LlKivd": ("kivd", "Lactococcus lactis"),
    "EcIlvC": ("ilvC", "Escherichia coli"),
    "EcIlvD": ("ilvD", "Escherichia coli"),
}

#: Targeting prefixes a submitter writes to mean "this protein is imported into the matrix".
#: `CovIX`/`CovIV` appear as typos of `CoxIV` in real deposits and are matched deliberately --
#: refusing to read a typo would drop a declared targeting sequence.
_MITOCHONDRIAL_TAGS: Final[tuple[str, ...]] = ("CoxIV", "CovIV", "COXIV", "CoxIv")

#: An N-terminal truncation suffix: `ScILV2N54` is Ilv2 lacking its first 54 residues, which is
#: how this literature removes a mitochondrial targeting sequence and relocates the enzyme to the
#: cytosol. The number is kept because it identifies the specific truncation.
_TRUNCATION = re.compile(r"^(?P<gene>[A-Za-z]{2}[A-Za-z0-9]+?)N(?P<residues>\d{1,3})$")


@dataclass(frozen=True, slots=True)
class DeclaredRun:
    """One run, with only the fields this module reads. Everything is the submitter's string."""

    run_accession: str
    study_accession: str
    biosample: str
    organism: str
    library_strategy: str
    library_selection: str
    sample_title: str
    genotype: str
    timepoint: str
    treatment: str
    replicate: str
    attributes: Mapping[str, str] = field(default_factory=dict)

    @property
    def sample_id(self) -> str:
        return f"YAA:SAMPLE:{self.run_accession}"


def load_run_attributes(path: Path | str) -> tuple[DeclaredRun, ...]:
    """Read the attributes TSV produced by the metadata fetch."""
    rows: list[DeclaredRun] = []
    with Path(path).open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            attributes = {
                key[len("attr_") :]: value
                for key, value in row.items()
                if key.startswith("attr_") and key != "attr_other" and (value or "").strip()
            }
            rows.append(
                DeclaredRun(
                    run_accession=row["run_accession"],
                    study_accession=row["study_accession"],
                    biosample=row.get("biosample", ""),
                    organism=row.get("organism", ""),
                    library_strategy=row.get("library_strategy", ""),
                    library_selection=row.get("library_selection", ""),
                    sample_title=row.get("sample_title", ""),
                    genotype=attributes.get("genotype", ""),
                    timepoint=attributes.get("timepoint") or attributes.get("time_point") or "",
                    treatment=attributes.get("treatment", ""),
                    replicate=attributes.get("replicate", ""),
                    attributes=attributes,
                )
            )
    return tuple(rows)


# -------------------------------------------------------------------------------- the construct


@dataclass(frozen=True, slots=True)
class Construct:
    """What a declared genotype string says was built. Zone H: this is a parse, not a quote."""

    parent_as_declared: str
    #: gene symbol -> ('mitochondrial_matrix' | 'cytosol' | 'unknown', the token as written)
    localization: Mapping[str, tuple[str, str]]
    source_organisms: Mapping[str, str]
    truncations: Mapping[str, int]
    raw: str

    @property
    def genes(self) -> tuple[str, ...]:
        return tuple(sorted(self.localization))

    def compartment_summary(self) -> str:
        places = {place for place, _ in self.localization.values()}
        if places == {"mitochondrial_matrix"}:
            return "all declared pathway enzymes mitochondrial"
        if places == {"cytosol"}:
            return "all declared pathway enzymes cytosolic"
        if not places:
            return "no pathway enzyme declared"
        return "mixed: " + ", ".join(
            f"{gene}={place}" for gene, (place, _) in sorted(self.localization.items())
        )


def native_compartments(conn: sqlite3.Connection) -> dict[str, str]:
    """Where the atlas's own curated reactions put each gene's product, natively.

    Read from `reaction_gene` joined to `reaction`, never hardcoded, so the localization a
    construct is parsed against is the same one the route enumerator gates on. A gene the curated
    pathways place in two compartments is left out rather than resolved by a rule invented here.
    """
    places: dict[str, set[str]] = {}
    for symbol, compartment in conn.execute(
        "SELECT rg.gene_symbol, r.compartment_id FROM reaction_gene rg "
        "JOIN reaction r ON r.id = rg.reaction_id WHERE r.compartment_id IS NOT NULL"
    ):
        places.setdefault(str(symbol), set()).add(str(compartment))
    return {symbol: next(iter(seen)) for symbol, seen in places.items() if len(seen) == 1}


def parse_construct(genotype: str, *, native: Mapping[str, str] | None = None) -> Construct:
    """Read genes, source organisms, targeting and truncations out of a declared genotype.

    The localization call is made on two declared features and nothing else:

    * an explicit targeting prefix (`pTEF2-CoxIV-LlAdhA29C8`) means the matrix;
    * an `N<digits>` truncation on a gene whose native product is mitochondrial (`ScILV2N54`)
      means the cytosol, because removing the presequence is what the truncation is for, and a
      heterologous bacterial gene with no presequence to begin with (`EcIlvC`) is cytosolic
      unless a tag says otherwise.

    A gene with neither feature keeps its native localization, which for the yeast `ILV` genes is
    the matrix. Where none of this applies the answer is ``'unknown'`` -- never a default.
    """
    parent = ""
    match = re.match(r"^\s*(?P<parent>[A-Za-z0-9._-]+)\s+with\b", genotype)
    if match:
        parent = match.group("parent")

    localization: dict[str, tuple[str, str]] = {}
    sources: dict[str, str] = {}
    truncations: dict[str, int] = {}

    tokens = re.split(r"[_\s;,]+", genotype)
    for token in tokens:
        cleaned = token.strip("-")
        if not cleaned:
            continue
        tagged = any(tag in cleaned for tag in _MITOCHONDRIAL_TAGS)
        for part in cleaned.split("-"):
            core = part.strip()
            if not core:
                continue
            truncated: int | None = None
            hit = _TRUNCATION.match(core)
            base = core
            if hit:
                base = hit.group("gene")
                truncated = int(hit.group("residues"))
            # Variant suffixes such as `LlAdhA29C8` or `EcIlvC6E6` name a mutant, not a new gene.
            for key, (symbol, organism) in _CONSTRUCT_GENES.items():
                if not base.startswith(key):
                    continue
                if tagged:
                    place = "mitochondrial_matrix"
                elif truncated is not None:
                    # A presequence truncation only relocates a protein that had one. Truncating a
                    # gene the atlas places in the cytosol anyway says nothing about compartment,
                    # so the native answer stands and the truncation is recorded on its own.
                    native_place = (native or {}).get(symbol)
                    place = (
                        "cytosol"
                        if native_place == "mitochondrial_matrix"
                        else (native_place or "unknown")
                    )
                elif organism != "Saccharomyces cerevisiae":
                    # A bacterial enzyme expressed in yeast has no presequence unless one was
                    # added, and the `tagged` branch above is where an added one is caught.
                    place = "cytosol"
                else:
                    place = (native or {}).get(symbol, "unknown")
                localization[symbol] = (place, core)
                sources[symbol] = organism
                if truncated is not None:
                    truncations[symbol] = truncated
                break

    return Construct(
        parent_as_declared=parent,
        localization=localization,
        source_organisms=sources,
        truncations=truncations,
        raw=genotype,
    )


# ---------------------------------------------------------------------------------- the strains


@dataclass(frozen=True, slots=True)
class StrainDeclaration:
    strain_id: str
    canonical_name: str
    organism_id: str
    strain_class: str
    genotype_as_declared: str
    construct: Construct
    run_accessions: tuple[str, ...]
    study_accession: str

    @property
    def sample_ids(self) -> tuple[str, ...]:
        return tuple(f"YAA:SAMPLE:{r}" for r in self.run_accessions)


def _strain_name(run: DeclaredRun) -> str:
    """The strain label the submitter used, taken from the sample title's first token.

    SRP342112 titles read `Y795 T14-1`: name, timepoint, replicate. Taking the first token is a
    parse of the title and is recorded as such; where a title is empty the BioSample accession is
    used instead, so a strain is never named after a guess.
    """
    title = run.sample_title.strip()
    if title:
        first = title.split()[0]
        if re.fullmatch(r"[A-Za-z]{1,4}[0-9]{1,5}[A-Za-z0-9-]*", first):
            return first

    # No usable title. Two deposits in this corpus name their strains only inside the genotype
    # or `source_name` attribute ("wild type genotype", "TRP5 defected strain"), and naming such
    # a strain after its BioSample would produce a row nobody can recognise and that no paper's
    # strain table could ever be matched against. So the declared description is slugged, and the
    # study prefix keeps two studies' "wild type" apart -- they are different backgrounds.
    described = (run.attributes.get("source_name") or run.genotype).strip()
    if described:
        slug = re.sub(r"[^a-z0-9]+", "-", described.lower()).strip("-")[:40]
        if slug:
            return f"{run.study_accession}-{slug}"
    return run.biosample or run.run_accession


def strain_declarations(
    runs: Iterable[DeclaredRun],
    *,
    organism_id: str,
    native: Mapping[str, str] | None = None,
) -> tuple[StrainDeclaration, ...]:
    """One declaration per distinct declared genotype within a study."""
    grouped: dict[tuple[str, str], list[DeclaredRun]] = {}
    for run in runs:
        if not run.genotype.strip():
            continue
        grouped.setdefault((run.study_accession, run.genotype.strip()), []).append(run)

    out: list[StrainDeclaration] = []
    for (study, genotype), members in sorted(grouped.items()):
        name = _strain_name(members[0])
        construct = parse_construct(genotype, native=native)
        out.append(
            StrainDeclaration(
                strain_id=f"YAA:STRAIN:{name.lower()}",
                canonical_name=name,
                organism_id=organism_id,
                strain_class="engineered" if construct.localization else "laboratory",
                genotype_as_declared=genotype,
                construct=construct,
                run_accessions=tuple(sorted(m.run_accession for m in members)),
                study_accession=study,
            )
        )
    return tuple(out)


# --------------------------------------------------------------------------------- the contexts

_HOUR = re.compile(r"hour\s*(?P<hours>\d+(?:\.\d+)?)", re.IGNORECASE)
_BARE_HOUR = re.compile(r"(?P<hours>\d+(?:\.\d+)?)\s*(?:h|hr|hour)s?\b", re.IGNORECASE)


def parse_timepoint_hours(declared: str) -> float | None:
    """`'T14 - hour 26'` -> 26.0. ``None`` when the string states no clock reading."""
    for pattern in (_HOUR, _BARE_HOUR):
        hit = pattern.search(declared)
        if hit:
            return float(hit.group("hours"))
    return None


def context_writes(
    runs: Sequence[DeclaredRun],
    *,
    study_accession: str,
    confidence: str = "medium",
    spec: StudyConditions | None = None,
) -> tuple[ContextWrite, ...]:
    """One context per distinct declared condition within a study.

    Which attributes *are* the conditions differs per deposit and is not guessable: SRP342112
    declares a `time_point`, SRP321884 declares two independent additions as `Yes`/`No`, and
    ERP116462 folds medium and stressor into one `growth_condition` sentence. A generic reader
    over "every attribute that varies" would sweep `replicate` and `source_name` into the context
    and split every replicate into its own vessel. So each study's mapping is declared in
    :data:`STUDY_CONDITIONS`, with the attribute keys named, and a study with no entry falls back
    to timepoint-and-treatment only.

    What is not declared is not in the facet set at all, which is what makes the resulting context
    honest about being thin.
    """
    resolved = spec or STUDY_CONDITIONS.get(study_accession) or StudyConditions(keys=())
    grouped: dict[tuple[tuple[str, str], ...], list[DeclaredRun]] = {}
    for run in runs:
        if run.study_accession != study_accession:
            continue
        key = resolved.key(run)
        grouped.setdefault(key, []).append(run)

    writes: list[ContextWrite] = []
    for key, members in sorted(grouped.items()):
        facets, label_parts = resolved.facets(key, study_accession=study_accession)
        if not facets:
            continue
        quote = "; ".join(f"{name}={value!r}" for name, value in key if value)
        writes.append(
            ContextWrite(
                label=f"{study_accession} {' '.join(label_parts) or 'declared conditions'}",
                facets=tuple(facets),
                sample_ids=tuple(sorted(m.sample_id for m in members)),
                source_quote=quote,
                study_accession=study_accession,
                confidence=confidence,
                dropped=resolved.dropped,
            )
        )
    return tuple(writes)


# --------------------------------------------------------------- what each study calls its axes


_PERCENT = re.compile(r"(?P<value>\d+(?:\.\d+)?)\s*%\s*\(?(?P<basis>v/v|w/v)?", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class StudyConditions:
    """Which declared attributes make up one study's condition, and how each becomes a facet.

    ``keys`` are the SAMPLE_ATTRIBUTE names read. Everything else in the block -- `replicate`,
    `source_name`, `cell_line`, `organism_part` -- is deliberately excluded: it identifies the
    sample or the strain, not the vessel it was grown in, and including it would make every
    replicate its own context and destroy the grouping the contrast needs.
    """

    keys: tuple[str, ...]
    #: Facets named by the source but with no column and no overflow home; recorded on the row.
    dropped: tuple[str, ...] = ()

    def key(self, run: DeclaredRun) -> tuple[tuple[str, str], ...]:
        if not self.keys:
            return (
                ("timepoint", run.timepoint.strip()),
                ("treatment", run.treatment.strip()),
            )
        return tuple((name, run.attributes.get(name, "").strip()) for name in self.keys)

    def facets(
        self, key: Sequence[tuple[str, str]], *, study_accession: str
    ) -> tuple[list[Facet], list[str]]:
        facets: list[Facet] = []
        labels: list[str] = []
        for name, value in key:
            facets.extend(_facets_for(name, value, labels))
        basis = " / ".join(f"{n}={v}" for n, v in key if v)
        if basis:
            facets.append(
                Facet(
                    name="sampling_basis",
                    state="recorded",
                    value=f"{basis} ({study_accession})",
                )
            )
        return facets, labels


def _facets_for(name: str, value: str, labels: list[str]) -> list[Facet]:
    """One declared attribute -> the facets it supports. Every branch is a curation decision.

    The two that are worth stating explicitly:

    * **`isobutanol_addition: No`** becomes `stressor.compound` at state ``'not_applicable'``,
      not an absent facet. The submitter recorded that no isobutanol was added; that is a
      statement, and PLAN.md C.5 keeps it distinct from never having said. It also hashes
      differently, so the treated and untreated vessels are two contexts rather than one.
    * **A concentration inside a sentence** ("SC medium with 1.3% (v/v) isobutanol") is parsed
      into `stressor.concentration` with the unit in the facet value, and the whole sentence is
      kept as `medium_name`'s as-reported shadow. The parse is Zone H; the sentence is Zone R.
    """
    facets: list[Facet] = []
    if not value:
        return facets

    lowered = value.lower()
    if name in {"timepoint", "time_point"}:
        hours = parse_timepoint_hours(value)
        if hours is not None:
            facets.append(Facet(name="time_h", state="recorded", value=hours))
            labels.append(f"{hours:g} h")
        else:
            labels.append(value)
        return facets

    if name.endswith("_addition"):
        compound = name[: -len("_addition")].replace("_", " ")
        if lowered in {"yes", "true", "1"}:
            facets.append(
                Facet(name="stressor.compound", state="recorded", value=compound)
                if compound == "isobutanol"
                else Facet(name="supplements", state="recorded", value=compound)
            )
            labels.append(f"+{compound}")
        elif lowered in {"no", "false", "0"}:
            facets.append(
                Facet(name="stressor.compound", state="not_applicable")
                if compound == "isobutanol"
                else Facet(name="supplements", state="not_applicable")
            )
            labels.append(f"-{compound}")
        return facets

    if name in {"growth_condition", "treatment", "medium", "growth_medium"}:
        medium = value.split(" with ")[0].split(" without ")[0].strip()
        if medium:
            facets.append(Facet(name="medium_name", state="recorded", value=medium))
        if "without isobutanol" in lowered:
            facets.append(Facet(name="stressor.compound", state="not_applicable"))
            labels.append("-isobutanol")
        elif "isobutanol" in lowered:
            facets.append(Facet(name="stressor.compound", state="recorded", value="isobutanol"))
            hit = _PERCENT.search(value)
            if hit:
                unit = (hit.group("basis") or "percent").lower()
                facets.append(
                    Facet(
                        name="stressor.concentration",
                        state="recorded",
                        value=f"{hit.group('value')} % {unit}",
                    )
                )
                labels.append(f"+isobutanol {hit.group('value')}% {unit}")
            else:
                labels.append("+isobutanol")
        else:
            labels.append(value[:40])
        return facets

    facets.append(Facet(name="sampling_basis", state="recorded", value=f"{name}: {value}"))
    labels.append(value[:30])
    return facets


#: Per-study condition mappings, each derived from the attribute keys that study actually
#: declares (`docs/drafts/omics/2026-09-22-study-inventory.md`). A study absent from this mapping
#: is read with the timepoint/treatment fallback, which is usually empty -- and an empty context
#: set is the correct outcome for a deposit that declared no conditions.
STUDY_CONDITIONS: Final[Mapping[str, StudyConditions]] = {
    # Declares only a clock reading per sample; medium and aeration are nowhere in the block.
    "SRP342112": StudyConditions(keys=("timepoint",)),
    # A 2x2 of two independent additions, each declared Yes/No on its own attribute.
    "SRP321884": StudyConditions(keys=("isobutanol_addition", "tryptophan_addition")),
    # Medium and stressor folded into one sentence; `age: 12` is declared but is not a condition
    # facet this schema has a home for, and is recorded as dropped rather than forced into time_h,
    # because the attribute does not say 12 of what.
    "ERP116462": StudyConditions(keys=("growth_condition",), dropped=("age",)),
}


# ----------------------------------------------------------------------------------- the writes


def write_strains(
    conn: sqlite3.Connection,
    declarations: Sequence[StrainDeclaration],
    *,
    curator: str,
    actor_kind: str,
) -> tuple[int, int, tuple[str, ...]]:
    """Write one `strain` and one `genotype` row per declaration, and link the samples.

    Returns ``(strains_written, samples_linked, notes)``. A strain whose id already exists is left
    exactly as it is -- a curator-promoted strain outranks a deposit's attribute string, and
    overwriting it here would let an SRA submitter's spelling silently replace a row somebody
    established by reading the paper.
    """
    written = 0
    linked = 0
    notes: list[str] = []
    for declaration in declarations:
        existing = conn.execute(
            "SELECT id, evidence FROM strain WHERE id = ?", (declaration.strain_id,)
        ).fetchone()
        if existing is None:
            conn.execute(
                "INSERT INTO strain (id, organism_id, canonical_name, class, zone, evidence, "
                "confidence) VALUES (?,?,?,?, 'R', ?, 'medium')",
                (
                    declaration.strain_id,
                    declaration.organism_id,
                    declaration.canonical_name,
                    declaration.strain_class,
                    (
                        f"declared in SRA study {declaration.study_accession} as "
                        f"genotype={declaration.genotype_as_declared!r} across runs "
                        f"{', '.join(declaration.run_accessions)}; name taken from the "
                        f"SAMPLE title; written by {curator} ({actor_kind})"
                    ),
                ),
            )
            written += 1
            genotype_id = f"YAA:GENOTYPE:{declaration.canonical_name.lower()}-sra"
            conn.execute(
                "INSERT INTO genotype (id, strain_id, as_reported, parsed_json, zone, evidence, "
                "confidence) VALUES (?,?,?,?, 'R', ?, 'medium') ON CONFLICT(id) DO NOTHING",
                (
                    genotype_id,
                    declaration.strain_id,
                    declaration.genotype_as_declared,
                    _construct_json(declaration.construct),
                    (
                        f"SRA SAMPLE_ATTRIBUTE 'genotype' for {declaration.canonical_name} in "
                        f"{declaration.study_accession}. parsed_json is a Zone H reading of that "
                        f"string: {declaration.construct.compartment_summary()}"
                    ),
                ),
            )
        else:
            notes.append(f"{declaration.canonical_name}: strain row already exists, left untouched")

        for sample_id in declaration.sample_ids:
            cursor = conn.execute(
                "UPDATE sample SET strain_id = ?, evidence = evidence || ? "
                "WHERE id = ? AND strain_id IS NULL",
                (
                    declaration.strain_id,
                    f"; strain {declaration.canonical_name} declared by the submitter",
                    sample_id,
                ),
            )
            linked += cursor.rowcount
    return written, linked, tuple(notes)


def _construct_json(construct: Construct) -> str:
    return json.dumps(
        {
            "zone": "H",
            "parent_as_declared": construct.parent_as_declared,
            "localization": {
                gene: {"compartment": place, "as_written": token}
                for gene, (place, token) in sorted(construct.localization.items())
            },
            "source_organisms": dict(sorted(construct.source_organisms.items())),
            "truncations": dict(sorted(construct.truncations.items())),
            "summary": construct.compartment_summary(),
        },
        sort_keys=True,
    )
