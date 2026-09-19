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
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

STOP = "*"


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
