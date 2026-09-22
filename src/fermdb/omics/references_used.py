"""Which quantification matrix a study's contrasts must be computed against.

SRP342112's producers carry a codon-optimized cassette whose reads leak onto the native loci of
the genes it duplicates -- measured at 14.1% of cassette abundance, which inflated the native
`ILV3` row by 10-25x because the cassette sits ~45x above the native gene. A contrast for that
study computed against the native-only index is not a weak measurement of those genes, it is a
measurement of the wrong thing. So the study is pinned to the construct-augmented matrix, and a
study with no cassette keeps the native one.

Pinning is per study rather than global because the augmented index only covers SRP342112's
construct; running another study against it would add eight rows that can never be anything but
zero and change nothing else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

__all__ = ["CASSETTE_STUDIES", "matrix_for", "reference_includes_constructs"]

#: study accession -> the matrices directory whose index contains that study's constructs.
CASSETTE_STUDIES: Final[dict[str, str]] = {"SRP342112": "matrices_transgene"}


def matrix_for(data_dir: Path, study_accession: str, *, name: str = "s288c.counts.tsv.gz") -> Path:
    """The counts matrix a contrast in this study must read.

    Falls back to the native-only matrix when the augmented one has not been built yet, so the
    pipeline still runs -- but `reference_includes_constructs` then reports False and every
    cassette-duplicated step is scored `confounded_by_construct` rather than silently trusted.
    """
    directory = CASSETTE_STUDIES.get(study_accession)
    if directory is not None:
        candidate = data_dir / directory / name
        if candidate.is_file():
            return candidate
    return data_dir / "matrices_mito" / name


def reference_includes_constructs(data_dir: Path, study_accession: str) -> bool:
    return matrix_for(data_dir, study_accession).parent.name != "matrices_mito"


def cassette_rows(matrix_path: Path) -> dict[str, str]:
    """gene symbol -> the matrix row that measures the *construct's* copy of it.

    Row ids follow the augmented index's own naming (``cassette_ILV3_MZ541859``,
    ``wildtype_EcIlvC``), so the mapping is read from the matrix rather than configured. These
    rows are the only honest measurement of an engineered step: the native locus shares reads
    with the cassette, the cassette row does not share reads with anything.

    They are also the cleanest label check available. A build declaring a cassette gene must show
    its cassette row and a parent must not, and the separation measured here is 0.5 TPM against
    ~11,600 -- four orders of magnitude, with no threshold to argue about.
    """
    import gzip

    mapping: dict[str, str] = {}
    if not matrix_path.is_file():
        return mapping
    with gzip.open(matrix_path, "rt") as handle:
        handle.readline()
        for line in handle:
            row = line.split("\t", 1)[0]
            if row.startswith("cassette_"):
                parts = row.split("_")
                if len(parts) >= 2:
                    mapping[parts[1]] = row
            elif row.startswith("wildtype_Ec"):
                # `wildtype_EcIlvC` measures the Y799 KARI, which was never codon-optimized and
                # has no cassette entry because no plasmid for that build is deposited anywhere.
                mapping[row[len("wildtype_Ec") :].lower().replace("ilvc", "ilvC")] = row
    return mapping
