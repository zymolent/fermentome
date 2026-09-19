"""Genetic code tables, keyed by encoding genome.

**The code follows the genome that carries the gene, not the compartment the protein ends up in**,
because translation happens where the ribosome is. A nuclear gene is translated on cytosolic
ribosomes under NCBI table 1 whatever its destination, so a presequence-targeted mitochondrial
construct needs **no recoding at all**. Only genes physically carried on mtDNA use table 3.

This matters most for the mitochondrial matrix, which holds proteins from both genomes: the
valine-branch enzymes Ilv2/Ilv5/Ilv3 are nuclear-encoded and imported, while Cox1/Cox2/Cob and a
handful of others are mtDNA-encoded. Asking "what code does the matrix use" is therefore a
malformed question, and `table_for_compartment` raises rather than answering it.

Table 3 differs from the standard code at six codons. The dangerous one is the whole `CUN` block
reading as threonine rather than leucine, which silently mistranslates a leucine-rich gene moved
**into mtDNA** — but not one merely targeted to the matrix from the nucleus.

Tables are built from the NCBI `AAs` strings rather than hand-written dictionaries, so a typo
would have to survive the round-trip check in `tests/test_genetic_code.py`.

History: this module originally keyed the code on compartment and mapped the matrix to table 3.
That was wrong and would have told a bench scientist to recode a construct that must not be
recoded. See docs/reference/CONVENTIONS.md "Genetic code and compartment".
"""

from __future__ import annotations

from dataclasses import dataclass

BASES = "TCAG"

#: Codons in NCBI order: base 1 slowest, base 3 fastest.
CODONS: tuple[str, ...] = tuple(b1 + b2 + b3 for b1 in BASES for b2 in BASES for b3 in BASES)

# NCBI translation table 1 — the Standard Code.
_AAS_TABLE_1 = "FFLLSSSSYY**CC*WLLLLPPPPHHQQRRRRIIIMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
_STARTS_TABLE_1 = ("TTG", "CTG", "ATG")

# NCBI translation table 3 — the Yeast Mitochondrial Code.
_AAS_TABLE_3 = "FFLLSSSSYY**CCWWTTTTPPPPHHQQRRRRIIMMTTTTNNKKSSRRVVVVAAAADDEEGGGG"
_STARTS_TABLE_3 = ("ATA", "ATG")

#: Codons reported absent from native *S. cerevisiae* mtDNA. Legal under table 3, but avoided
#: in recoded sequences because the mitochondrial tRNA set may not read them efficiently.
ABSENT_IN_YEAST_MITO: frozenset[str] = frozenset({"CGA", "CGC"})


@dataclass(frozen=True)
class GeneticCode:
    """One NCBI translation table."""

    table_id: int
    name: str
    codon_to_aa: dict[str, str]
    start_codons: tuple[str, ...]

    def translate_codon(self, codon: str) -> str:
        """Return the one-letter amino acid, or `X` for a codon containing an ambiguity code."""
        return self.codon_to_aa.get(codon.upper(), "X")

    def synonyms(self, aa: str) -> tuple[str, ...]:
        """Every codon encoding `aa` under this table, in NCBI order."""
        return tuple(c for c in CODONS if self.codon_to_aa[c] == aa)


def _build(table_id: int, name: str, aas: str, starts: tuple[str, ...]) -> GeneticCode:
    if len(aas) != 64:
        raise ValueError(f"table {table_id}: expected 64 amino acids, got {len(aas)}")
    return GeneticCode(table_id, name, dict(zip(CODONS, aas, strict=True)), starts)


TABLE_1 = _build(1, "Standard", _AAS_TABLE_1, _STARTS_TABLE_1)
TABLE_3 = _build(3, "Yeast Mitochondrial", _AAS_TABLE_3, _STARTS_TABLE_3)

TABLES: dict[int, GeneticCode] = {1: TABLE_1, 3: TABLE_3}

#: Which table each **encoding genome** translates by. This — not the destination compartment —
#: is what determines the code, because translation happens where the ribosome is, not where the
#: protein ends up.
ENCODING_GENOME_TABLE: dict[str, int] = {
    "nuclear": 1,  # transcribed in the nucleus, translated on cytosolic ribosomes
    "mitochondrial": 3,  # transcribed and translated inside the matrix
}

#: Which genomes can encode a protein found in each compartment.
#:
#: The mitochondrial matrix is the one that matters and the one that is routinely got wrong: it
#: holds proteins from **both** genomes. The valine-branch enzymes Ilv2/Ilv5/Ilv3 are
#: nuclear-encoded, translated on cytosolic ribosomes under table 1, and then imported — so a
#: construct targeted there with a presequence needs **no recoding at all**. Only the handful of
#: genes actually carried on mtDNA use table 3.
#:
#: The intermembrane space holds only nuclear-encoded proteins in *S. cerevisiae* (unverified);
#: mtDNA encodes matrix and inner-membrane products, not soluble IMS residents.
COMPARTMENT_ENCODING_GENOMES: dict[str, tuple[str, ...]] = {
    "cytosol": ("nuclear",),
    "nucleus": ("nuclear",),
    "endoplasmic_reticulum": ("nuclear",),
    "peroxisome": ("nuclear",),
    "vacuole": ("nuclear",),
    "extracellular": ("nuclear",),
    "mitochondrial_ims": ("nuclear",),
    "mitochondrial_matrix": ("nuclear", "mitochondrial"),
    "mitochondrial_inner_membrane": ("nuclear", "mitochondrial"),
}


class AmbiguousCompartmentError(ValueError):
    """The compartment alone does not determine the genetic code."""


def table_for_encoding_genome(encoding_genome: str) -> GeneticCode:
    """Return the code a gene is translated by, given the genome that carries it."""
    try:
        return TABLES[ENCODING_GENOME_TABLE[encoding_genome]]
    except KeyError as exc:
        known = ", ".join(sorted(ENCODING_GENOME_TABLE))
        raise KeyError(f"unknown encoding genome {encoding_genome!r}; known: {known}") from exc


def table_for_compartment(compartment: str, encoding_genome: str | None = None) -> GeneticCode:
    """Return the code that applies to a sequence in `compartment`.

    Raises rather than guessing, in both directions:

    * an unrecognised compartment raises `KeyError`, because silently assuming the standard code
      is the failure this module exists to prevent;
    * a compartment served by **both** genomes raises `AmbiguousCompartmentError` unless
      `encoding_genome` is given. This is deliberate and is the point of the whole module: asking
      "what code does the mitochondrial matrix use?" is a malformed question, and answering it
      with table 3 would tell someone to recode a nuclear construct that must not be recoded.
    """
    try:
        genomes = COMPARTMENT_ENCODING_GENOMES[compartment]
    except KeyError as exc:
        known = ", ".join(sorted(COMPARTMENT_ENCODING_GENOMES))
        raise KeyError(f"unknown compartment {compartment!r}; known: {known}") from exc

    if encoding_genome is not None:
        if encoding_genome not in genomes:
            raise ValueError(
                f"{compartment!r} holds no {encoding_genome!r}-encoded proteins; "
                f"it is served by: {', '.join(genomes)}"
            )
        return table_for_encoding_genome(encoding_genome)

    if len(genomes) > 1:
        raise AmbiguousCompartmentError(
            f"{compartment!r} holds proteins from both genomes ({', '.join(genomes)}), so the "
            "compartment does not determine the code. Pass encoding_genome='nuclear' for a "
            "presequence-targeted construct (no recoding needed) or 'mitochondrial' for a gene "
            "placed into mtDNA (recoding required)."
        )
    return table_for_encoding_genome(genomes[0])


def codons_of(seq: str) -> list[str]:
    """Split a nucleotide sequence into whole codons, discarding a trailing partial codon."""
    s = seq.upper().replace("U", "T")
    return [s[i : i + 3] for i in range(0, len(s) - len(s) % 3, 3)]


def translate(seq: str, code: GeneticCode, *, to_stop: bool = False) -> str:
    """Translate a nucleotide sequence under `code`."""
    out: list[str] = []
    for codon in codons_of(seq):
        aa = code.translate_codon(codon)
        if aa == "*" and to_stop:
            break
        out.append(aa)
    return "".join(out)


@dataclass(frozen=True)
class CodonDifference:
    """One codon whose meaning depends on which table reads it."""

    index: int  # 0-based codon index
    codon: str
    aa_table_1: str
    aa_table_3: str

    def __str__(self) -> str:
        return (
            f"codon {self.index + 1} {self.codon}: "
            f"table1={self.aa_table_1} table3={self.aa_table_3}"
        )


#: The six codons that mean different things in the two tables.
AMBIGUOUS_CODONS: tuple[str, ...] = tuple(
    c for c in CODONS if TABLE_1.codon_to_aa[c] != TABLE_3.codon_to_aa[c]
)


def diff_tables(seq: str) -> list[CodonDifference]:
    """Codons in `seq` whose amino acid differs between table 1 and table 3.

    An empty result means the sequence is *dual-safe*: it encodes the same protein wherever it is
    translated, so one ORF can be tested in the cytosol and in the matrix without recoding. That
    is directly useful for the strategy C versus strategy E comparison in
    `docs/design/MITOCHONDRIAL_PROGRAM.md` §4.
    """
    return [
        CodonDifference(i, codon, TABLE_1.codon_to_aa[codon], TABLE_3.codon_to_aa[codon])
        for i, codon in enumerate(codons_of(seq))
        if codon in AMBIGUOUS_CODONS
    ]


def at_fraction(seq: str) -> float:
    """A/T fraction, ignoring anything that is not an unambiguous base."""
    s = seq.upper().replace("U", "T")
    counted = [b for b in s if b in "ACGT"]
    if not counted:
        return 0.0
    return sum(1 for b in counted if b in "AT") / len(counted)
