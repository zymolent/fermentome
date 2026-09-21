"""Codon recoding between the standard and yeast mitochondrial genetic codes.

Three jobs, from `docs/design/MITOCHONDRIAL_PROGRAM.md` §2.2:

* a gene placed **into** mtDNA must be recoded for table 3;
* an mtDNA gene expressed **allotopically** from the nucleus must be recoded for table 1;
* a gene merely **targeted** to the matrix as a nuclear-encoded protein needs no recoding,
  because translation still happens on cytosolic ribosomes.

There is also a fourth, which falls out of the first two and is the most useful in practice:
a **dual-safe** recoding, which encodes the same protein under both tables. Every amino acid has
at least one dual-safe codon, so this always succeeds — and it means one construct can be tested
cytosolically and mitochondrially without rebuilding it.

**The published control.** PLAN.md Q's phase-0 acceptance requires the recoder to round-trip a
known mitochondrial gene *and* to be held against a published recoded marker. That marker is
ARG8m, and its sequence is not in this project's literature corpus — it had to come from GenBank
(U31093.1). `load_recoding_controls` reads the fetched artifacts out of
`data/mitochondria/recoding_controls.yaml`, checksum-verified, and `compare_codons` is the
positional comparison the acceptance test makes against them. The answer that comparison returns
is *not* equality, and that is recorded rather than smoothed over: see the data file's header and
`tests/test_recode.py`.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from .genetic_code import (
    ABSENT_IN_YEAST_MITO,
    TABLE_1,
    TABLE_3,
    CodonDifference,
    GeneticCode,
    at_fraction,
    codons_of,
    diff_tables,
    translate,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance, not behaviour
    from .config import Settings

STOP = "*"

#: The curated, committed file holding the published artifacts the recoder is judged against.
#: Repo tier, not derived output: it is fetched-once reference data with accessions attached, and
#: nothing in this codebase regenerates it.
RECODING_CONTROLS_FILE: Final[str] = "recoding_controls.yaml"


def _rank(codon: str) -> tuple[int, int, str]:
    """Preference order for synonymous codons.

    Yeast mtDNA is strongly AT-rich, so AT-rich synonyms are preferred; codons reported absent
    from native yeast mtDNA are pushed last; ties break lexicographically so the output is
    deterministic and diffable.
    """
    at = sum(1 for b in codon if b in "AT")
    return (1 if codon in ABSENT_IN_YEAST_MITO else 0, -at, codon)


def dual_safe_codons(aa: str) -> tuple[str, ...]:
    """Codons encoding `aa` identically under both tables, best first."""
    both = [c for c in TABLE_1.synonyms(aa) if TABLE_3.codon_to_aa[c] == aa]
    return tuple(sorted(both, key=_rank))


def codons_for(aa: str, code: GeneticCode) -> tuple[str, ...]:
    """Codons encoding `aa` under one table, best first."""
    return tuple(sorted(code.synonyms(aa), key=_rank))


@dataclass
class RecodeResult:
    """A recoded sequence and everything needed to judge it."""

    sequence: str
    protein: str
    mode: str
    changed: int
    total_codons: int
    at_before: float
    at_after: float
    absent_codons_remaining: list[int] = field(default_factory=list)
    residual_ambiguity: list[CodonDifference] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def is_dual_safe(self) -> bool:
        return not self.residual_ambiguity

    def summary(self) -> str:
        lines = [
            f"mode              {self.mode}",
            f"codons            {self.total_codons}",
            f"changed           {self.changed} ({self.changed / max(self.total_codons, 1):.1%})",
            f"AT content        {self.at_before:.1%} -> {self.at_after:.1%}",
            f"dual-safe         {'yes' if self.is_dual_safe else 'NO'}",
        ]
        if self.residual_ambiguity:
            lines.append(f"ambiguous codons  {len(self.residual_ambiguity)}")
            for d in self.residual_ambiguity[:5]:
                lines.append(f"  {d}")
            if len(self.residual_ambiguity) > 5:
                lines.append(f"  ... and {len(self.residual_ambiguity) - 5} more")
        if self.absent_codons_remaining:
            lines.append(
                f"CGA/CGC remaining {len(self.absent_codons_remaining)} "
                "(absent from native yeast mtDNA)"
            )
        lines.extend(f"note              {n}" for n in self.notes)
        return "\n".join(lines)


class RecodeError(ValueError):
    """Raised when a sequence cannot be recoded as asked."""


def recode(seq: str, *, source_table: int = 1, mode: str = "dual_safe") -> RecodeResult:
    """Recode a coding sequence.

    `mode` is one of:

    * `dual_safe`  — same protein under both tables (recommended; always achievable)
    * `to_table3`  — legal and unambiguous for the mitochondrial matrix
    * `to_table1`  — legal and unambiguous for cytosolic translation

    `source_table` says which code the input is *written in*, which is what determines the protein
    being preserved. Getting this wrong silently produces a different protein, so it is explicit
    and has no clever default.
    """
    if mode not in {"dual_safe", "to_table3", "to_table1"}:
        raise RecodeError(f"unknown mode {mode!r}")

    source = {1: TABLE_1, 3: TABLE_3}.get(source_table)
    if source is None:
        raise RecodeError(f"unsupported source_table {source_table!r}; use 1 or 3")

    original = "".join(codons_of(seq))
    codons = codons_of(seq)
    if not codons:
        raise RecodeError("empty or sub-codon sequence")

    protein = translate(original, source)
    if "X" in protein:
        bad = protein.index("X")
        raise RecodeError(
            f"codon {bad + 1} ({codons[bad]}) is not an unambiguous DNA codon; "
            "resolve ambiguity codes before recoding"
        )

    target = TABLE_3 if mode == "to_table3" else TABLE_1
    out: list[str] = []
    changed = 0
    notes: list[str] = []

    for codon in codons:
        aa = source.codon_to_aa[codon]
        candidates = dual_safe_codons(aa) if mode == "dual_safe" else codons_for(aa, target)
        if not candidates:
            raise RecodeError(f"no codon encodes {aa!r} under the requested mode")
        # Keep the original codon when it is already among the acceptable ones and is not a
        # codon we actively avoid — an unnecessary change is a change someone has to review.
        keep = codon in candidates and codon not in ABSENT_IN_YEAST_MITO
        chosen = codon if keep else candidates[0]
        if chosen != codon:
            changed += 1
        out.append(chosen)

    recoded = "".join(out)

    # Internal stops are worth saying out loud rather than leaving for the reader to notice.
    internal = [i for i, c in enumerate(out[:-1]) if target.codon_to_aa[c] == STOP]
    if internal:
        notes.append(f"{len(internal)} internal stop codon(s) under table {target.table_id}")
    if out and target.codon_to_aa[out[-1]] != STOP:
        notes.append("sequence does not end in a stop codon")
    if mode == "to_table3" and out[0] not in TABLE_3.start_codons:
        notes.append(f"first codon {out[0]} is not a table 3 start codon (ATA, ATG)")

    return RecodeResult(
        sequence=recoded,
        protein=protein,
        mode=mode,
        changed=changed,
        total_codons=len(codons),
        at_before=at_fraction(original),
        at_after=at_fraction(recoded),
        absent_codons_remaining=[i for i, c in enumerate(out) if c in ABSENT_IN_YEAST_MITO],
        residual_ambiguity=diff_tables(recoded),
        notes=notes,
    )


@dataclass
class SafetyReport:
    """Whether a sequence may be filed against a compartment."""

    compartment: str
    table_id: int
    accepted: bool
    encoding_genome: str = "nuclear"
    reasons: list[str] = field(default_factory=list)
    differences: list[CodonDifference] = field(default_factory=list)
    cun_codons: list[int] = field(default_factory=list)
    absent_codons: list[int] = field(default_factory=list)
    at: float = 0.0

    def summary(self) -> str:
        head = "ACCEPTED" if self.accepted else "REJECTED"
        lines = [
            f"{head}  compartment={self.compartment} genome={self.encoding_genome} "
            f"table={self.table_id} at={self.at:.1%}"
        ]
        lines.extend(f"  - {r}" for r in self.reasons)
        return "\n".join(lines)


def check_compartment_safety(
    seq: str, compartment: str, *, encoding_genome: str | None = None
) -> SafetyReport:
    """Decide whether a sequence can be stored against a compartment.

    This is the phase-0 acceptance criterion in PLAN.md Q: *a sequence filed against
    `mitochondrial_matrix` carrying an unrecoded `CUN` run is rejected* — but only when that
    sequence is destined for **mtDNA**. The same sequence targeted to the matrix by a
    presequence is nuclear-encoded, translated on cytosolic ribosomes, and must NOT be recoded.

    `encoding_genome` is therefore required for any compartment served by both genomes; omitting
    it raises rather than guessing. Conflating the two is the most expensive modelling error
    available here (docs/design/MITOCHONDRIAL_PROGRAM.md §4).

    The general test: translate under both tables and compare. If the protein differs, the
    sequence's meaning depends on where it is read, which is precisely the hazard.
    """
    from .genetic_code import table_for_compartment

    code = table_for_compartment(compartment, encoding_genome)
    genome = encoding_genome or ("mitochondrial" if code.table_id == 3 else "nuclear")
    differences = diff_tables(seq)
    codons = codons_of(seq)
    cun = [i for i, c in enumerate(codons) if c.startswith("CT")]
    absent = [i for i, c in enumerate(codons) if c in ABSENT_IN_YEAST_MITO]

    reasons: list[str] = []
    accepted = True

    if code.table_id == 3:
        if cun:
            accepted = False
            reasons.append(
                f"{len(cun)} CUN codon(s) at positions "
                f"{', '.join(str(i + 1) for i in cun[:8])}"
                f"{' ...' if len(cun) > 8 else ''} — these read as threonine under table 3, "
                "not leucine. Recode before filing against a mitochondrial compartment."
            )
        if any(c == "TGA" for c in codons[:-1]):
            reasons.append("internal TGA reads as tryptophan under table 3, not stop")
        if absent:
            reasons.append(
                f"{len(absent)} CGA/CGC codon(s) — reported absent from native yeast mtDNA"
            )
        if codons and codons[-1] == "TGA":
            accepted = False
            reasons.append("terminal TGA is tryptophan under table 3; use TAA or TAG")
    elif differences:
        reasons.append(
            f"{len(differences)} codon(s) translate differently under table 3 — fine here, "
            "but this sequence is not portable to a mitochondrial compartment"
        )

    if accepted and not reasons:
        reasons.append("no table-dependent codons; sequence is dual-safe")

    return SafetyReport(
        compartment=compartment,
        table_id=code.table_id,
        encoding_genome=genome,
        accepted=accepted,
        reasons=reasons,
        differences=differences,
        cun_codons=cun,
        absent_codons=absent,
        at=at_fraction(seq),
    )


# ------------------------------------------------------------------- the published control set


class RecodingControlError(RuntimeError):
    """The published-control file is missing, malformed, or no longer matches its checksum."""


@dataclass(frozen=True)
class RecodingControl:
    """One published sequence, with the accession that makes it evidence rather than an opinion.

    These are Zone R artifacts: exactly what NCBI Nucleotide returned for the stated accession and
    region. `protein` is the record's own translation under `translation_table`, carried alongside
    the nucleotides so that a test can check this project's `translate` against NCBI's curators
    rather than against itself.
    """

    id: str
    role: str
    gene: str
    accession: str
    region: str
    length_nt: int
    encoding_genome: str
    translation_table: int
    protein_accession: str | None
    protein_length_aa: int
    sequence: str
    protein: str
    checksum_sha256: str
    source_url: str
    note: str
    evidence: str
    confidence: str


def _controls_path(settings: Settings) -> Path:
    # Beside the other curated mitochondrial data, under the repo tier -- committed curation,
    # never auto-created, exactly like `data/mitochondria/activator_map.yaml`.
    return Path(settings.repo_root) / "data" / "mitochondria" / RECODING_CONTROLS_FILE


def _clean(sequence: str) -> str:
    """Strip the line wrapping a YAML block scalar introduces, and normalise case."""
    return "".join(sequence.split()).upper()


def _require(row: dict[str, Any], key: str, where: str) -> Any:
    if key not in row:
        raise RecodingControlError(f"{where}: missing required key {key!r}")
    return row[key]


def _load_controls_document(settings: Settings, path: Path | None) -> tuple[dict[str, Any], Path]:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - exercised only without the dependency
        raise RecodingControlError("PyYAML is required to read the recoding controls") from exc

    source = _controls_path(settings) if path is None else path
    if not source.is_file():
        raise RecodingControlError(
            f"no recoding controls at {source}. They are curated, committed reference data "
            "fetched from NCBI (PLAN.md Q phase 0) and are not generated."
        )
    document = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
    if not isinstance(document, dict):
        raise RecodingControlError(f"{source}: top level must be a mapping")
    return document, source


def load_recoding_controls(
    settings: Settings, *, path: Path | None = None
) -> dict[str, RecodingControl]:
    """Read the published controls, verifying every checksum and declared length.

    Raises rather than returning what it found. A control sequence that has drifted from its
    recorded checksum silently changes what the phase-0 acceptance test *means* -- the test would
    still pass, against a different sequence -- so a mismatch is fatal here and not a warning.
    """
    document, source = _load_controls_document(settings, path)
    rows = document.get("sequences")
    if not isinstance(rows, list) or not rows:
        raise RecodingControlError(f"{source}: 'sequences' must be a non-empty list")

    controls: dict[str, RecodingControl] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise RecodingControlError(f"{source}: sequences[{index}] is not a mapping")
        where = f"{source}: sequences[{index}]"
        control_id = str(_require(row, "id", where))
        if control_id in controls:
            raise RecodingControlError(f"{where}: duplicate id {control_id!r}")
        sequence = _clean(str(_require(row, "sequence", where)))

        declared_length = int(_require(row, "length_nt", where))
        if len(sequence) != declared_length:
            raise RecodingControlError(
                f"{where} ({control_id}): length_nt says {declared_length} but the stored "
                f"sequence is {len(sequence)} nt"
            )
        digest = hashlib.sha256(sequence.encode("ascii")).hexdigest()
        recorded = str(_require(row, "checksum_sha256", where))
        if digest != recorded:
            raise RecodingControlError(
                f"{where} ({control_id}): checksum mismatch -- recorded {recorded}, computed "
                f"{digest}. The stored sequence no longer matches the accession it claims."
            )

        protein_accession = row.get("protein_accession")
        controls[control_id] = RecodingControl(
            id=control_id,
            role=str(_require(row, "role", where)),
            gene=str(_require(row, "gene", where)),
            accession=str(_require(row, "accession", where)),
            region=str(_require(row, "region", where)),
            length_nt=declared_length,
            encoding_genome=str(_require(row, "encoding_genome", where)),
            translation_table=int(_require(row, "translation_table", where)),
            protein_accession=None if protein_accession is None else str(protein_accession),
            protein_length_aa=int(_require(row, "protein_length_aa", where)),
            sequence=sequence,
            protein=_clean(str(_require(row, "protein", where))),
            checksum_sha256=recorded,
            source_url=str(_require(row, "source_url", where)),
            note=str(_require(row, "note", where)),
            evidence=str(_require(row, "evidence", where)),
            confidence=str(_require(row, "confidence", where)),
        )
    return controls


def load_recoding_comparison(settings: Settings, *, path: Path | None = None) -> dict[str, Any]:
    """Read the recorded census of recoder output against the published marker.

    Kept beside the sequences rather than inlined in a test so that the numbers and the paragraph
    explaining them live together: the recoder does **not** reproduce ARG8m codon-for-codon, and
    the shape of that disagreement is the finding, not an inconvenience.
    """
    document, source = _load_controls_document(settings, path)
    comparison = document.get("comparison")
    if not isinstance(comparison, dict):
        raise RecodingControlError(f"{source}: 'comparison' must be a mapping")
    return comparison


@dataclass(frozen=True)
class CodonComparison:
    """A strictly positional codon-by-codon comparison of two equal-length coding sequences."""

    total_codons: int
    identical_codons: int
    identical_nucleotides: int
    #: 0-based codon indices where the two sequences differ.
    differing_positions: tuple[int, ...]
    #: Of those, the ones encoding the same residue under `code` -- a preference difference only.
    synonymous_positions: tuple[int, ...]
    #: Of those, the ones encoding a *different* residue -- a real disagreement about the protein.
    substitution_positions: tuple[int, ...]

    @property
    def is_identical(self) -> bool:
        return not self.differing_positions

    @property
    def encodes_the_same_protein(self) -> bool:
        return not self.substitution_positions


def compare_codons(left: str, right: str, code: GeneticCode) -> CodonComparison:
    """Compare two coding sequences codon by codon, classifying every difference.

    Requires equal length, because an alignment would be a second thing to get wrong and the one
    comparison this exists for -- recoder output against published ARG8m -- is length-matched by
    construction (both 1,272 nt, the same 424 codons, no indels).
    """
    left_codons = codons_of(left)
    right_codons = codons_of(right)
    if len(left_codons) != len(right_codons):
        raise RecodeError(
            f"cannot compare {len(left_codons)} codons against {len(right_codons)}; "
            "compare_codons is positional and does not align"
        )

    differing = tuple(
        i for i, (a, b) in enumerate(zip(left_codons, right_codons, strict=True)) if a != b
    )
    synonymous = tuple(
        i
        for i in differing
        if code.codon_to_aa[left_codons[i]] == code.codon_to_aa[right_codons[i]]
    )
    synonymous_set = set(synonymous)
    return CodonComparison(
        total_codons=len(left_codons),
        identical_codons=len(left_codons) - len(differing),
        identical_nucleotides=sum(1 for a, b in zip(left, right, strict=True) if a == b),
        differing_positions=differing,
        synonymous_positions=synonymous,
        substitution_positions=tuple(i for i in differing if i not in synonymous_set),
    )
