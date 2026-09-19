"""The annotation source registry: `data/annotation/annotation_sources.yaml`.

Loading follows the exact pattern `fermdb.omics.load_dataset_families`/`dataset_families_path`
already use for `data/omics/dataset_families.yaml` (see that module's docstring for why: no
dedicated `env/paths.yaml` key is added for a single repo-tier file, `paths.py`/`config.py` are
outside this task's file list, and a fixed sub-path off the already-configurable `repo_root`
follows the same pattern `fermdb.paths` itself uses elsewhere).

This module also owns the one piece of domain logic every GO-backed importer needs: mapping a raw
GO evidence code onto this project's `confidence` vocabulary without discarding the code itself.
docs/reference/CONVENTIONS.md ("Evidence") requires evidence carried, not flattened -- IDA
(Inferred from Direct Assay) is direct experimental evidence, IEA (Inferred from Electronic
Annotation) is computational, and collapsing both to one confidence value would erase exactly the
distinction that lets a later reader judge how strong a given GO annotation really is.
`recommended_confidence_for_go_evidence` is a documented, overridable EDITORIAL DEFAULT an
importer may use when writing a fresh `gene_annotation` row -- a curator reviewing the row later is
always free to override it, the same way `data/literature/query_families.yaml`'s
`product_tier`/`default_disposition` classification is flagged there as "an editorial
classification call by this implementation... flagged here for the reviewer to confirm or
override". It is not itself a fact recalled from a source, so it is documented as a policy choice,
not asserted as verified domain knowledge.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Final

import yaml

from ..config import Settings

__all__ = [
    "GO_EVIDENCE_CATEGORIES",
    "AnnotationSource",
    "AnnotationSourcesError",
    "UnknownGoEvidenceCodeError",
    "annotation_sources_path",
    "go_evidence_category",
    "load_annotation_sources",
    "recommended_confidence_for_go_evidence",
    "resolve_source_url",
    "source_by_id",
    "sources_for_organism",
]

#: Must match `gene_annotation.source`'s CHECK constraint in src/fermdb/db/schema.sql exactly.
#: tests/test_annotate.py asserts the two stay in agreement, the same way
#: tests/test_schema.py:test_encoding_genome_rows_agree_with_genetic_code_module keeps
#: genetic_code.py and schema.sql's seed rows from drifting apart independently of each other.
KNOWN_SOURCE_IDS: Final[frozenset[str]] = frozenset(
    {
        "sgd_go",
        "uniprot_goa",
        "kegg",
        "pfam",
        "interpro",
        "uniprot",
        "tcdb",
        "complex_portal",
        "yeastract",
        "sgd_phenotype",
    }
)

_CONFIDENCE_VALUES: Final[frozenset[str]] = frozenset({"unverified", "low", "medium", "high"})

_VALID_COVERS: Final[frozenset[str]] = frozenset(
    {
        "go_term",
        "pathway_ko_ec",
        "protein_domain",
        "cofactor_and_localization",
        "transporter_family",
        "protein_complex",
        "transcription_factor_target",
        "phenotype",
    }
)


class AnnotationSourcesError(ValueError):
    """`data/annotation/annotation_sources.yaml` is missing, malformed, or internally
    inconsistent."""


@dataclass(frozen=True)
class AnnotationSource:
    """One row of `data/annotation/annotation_sources.yaml`.

    `redistributable` gates what an importer in `importers.py` may store: `False` means
    identifiers and a resolvable link only, never a copied-out reaction list, pathway map, or bulk
    export (see that file's KEGG/TCDB/YEASTRACT importers).
    """

    id: str
    name: str
    organisms: tuple[str, ...]
    covers: str
    url_pattern: str
    license: str
    redistributable: bool
    update_cadence: str
    notes: str | None
    evidence: str
    confidence: str


def load_annotation_sources(path: str | Path) -> list[AnnotationSource]:
    """Parse `data/annotation/annotation_sources.yaml`'s `sources` list.

    No path is hardcoded here: the caller resolves `path` from `Settings` (repo tier), per
    docs/reference/CONVENTIONS.md ("Paths and configuration") -- see `annotation_sources_path`.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise AnnotationSourcesError(f"no annotation sources file at {file_path}")
    with file_path.open("r", encoding="utf-8") as handle:
        document = yaml.safe_load(handle)
    if not isinstance(document, dict) or "sources" not in document:
        raise AnnotationSourcesError(f"{file_path}: expected a mapping with a top-level 'sources'")
    raw_sources = document["sources"]
    if not isinstance(raw_sources, list):
        raise AnnotationSourcesError(f"{file_path}: 'sources' must be a list")

    result: list[AnnotationSource] = []
    seen: set[str] = set()
    for index, row in enumerate(raw_sources):
        if not isinstance(row, dict):
            raise AnnotationSourcesError(f"{file_path}: sources[{index}] must be a mapping")
        try:
            source_id = str(row["id"])
            name = str(row["name"])
            organisms_raw = row["organisms"]
            covers = str(row["covers"])
            url_pattern = str(row["url_pattern"])
            license_ = str(row["license"])
            redistributable = row["redistributable"]
            update_cadence = str(row["update_cadence"])
            evidence = str(row["evidence"])
            confidence = str(row["confidence"])
        except KeyError as exc:
            raise AnnotationSourcesError(f"{file_path}: sources[{index}] missing {exc}") from exc

        if source_id in seen:
            raise AnnotationSourcesError(f"{file_path}: duplicate source id {source_id!r}")
        seen.add(source_id)

        if not isinstance(organisms_raw, list) or not organisms_raw:
            raise AnnotationSourcesError(
                f"{file_path}: sources[{index}] ({source_id!r}) "
                "'organisms' must be a non-empty list"
            )
        if covers not in _VALID_COVERS:
            raise AnnotationSourcesError(
                f"{file_path}: sources[{index}] ({source_id!r}) has covers {covers!r}; "
                f"must be one of {sorted(_VALID_COVERS)}"
            )
        if not isinstance(redistributable, bool):
            raise AnnotationSourcesError(
                f"{file_path}: sources[{index}] ({source_id!r}) 'redistributable' must be a bool"
            )
        if confidence not in _CONFIDENCE_VALUES:
            raise AnnotationSourcesError(
                f"{file_path}: sources[{index}] ({source_id!r}) has confidence {confidence!r}; "
                f"must be one of {sorted(_CONFIDENCE_VALUES)}"
            )

        result.append(
            AnnotationSource(
                id=source_id,
                name=name,
                organisms=tuple(str(o) for o in organisms_raw),
                covers=covers,
                url_pattern=url_pattern,
                license=license_,
                redistributable=bool(redistributable),
                update_cadence=update_cadence,
                notes=row.get("notes"),
                evidence=evidence,
                confidence=confidence,
            )
        )
    return result


def annotation_sources_path(settings: Settings) -> Path:
    """`data/annotation/annotation_sources.yaml`, resolved off `settings.repo_root`.

    There is no dedicated `env/paths.yaml` key for this file, for the same reason
    `fermdb.omics.dataset_families_path` gives for its own file: adding one means keeping
    `fermdb.paths._BUILTIN_DEFAULTS` in sync with it, and `paths.py`/`config.py` are outside this
    task's file list. A fixed sub-path off the already-configurable `repo_root` is the established
    pattern for exactly this situation elsewhere in the codebase.
    """
    return settings.repo_root / "data" / "annotation" / "annotation_sources.yaml"


def source_by_id(sources: list[AnnotationSource], source_id: str) -> AnnotationSource:
    """The one source named `source_id`, or raise `KeyError` naming what *is* available."""
    for source in sources:
        if source.id == source_id:
            return source
    known = ", ".join(sorted(s.id for s in sources))
    raise KeyError(f"unknown annotation source {source_id!r}; known sources: {known}")


def sources_for_organism(
    sources: list[AnnotationSource], organism: str
) -> tuple[AnnotationSource, ...]:
    """Every source whose `organisms` names `organism` explicitly, or is scoped `'broad'`."""
    return tuple(s for s in sources if organism in s.organisms or "broad" in s.organisms)


def resolve_source_url(source: AnnotationSource, **fields: str) -> str:
    """Fill `source.url_pattern`'s `{placeholder}` fields with `fields`.

    Raises `AnnotationSourcesError` naming the exact mismatch rather than letting a plain
    `KeyError`/`IndexError` from `str.format` surface -- the pattern and the caller's fields are
    two independently-maintained things (this file vs. an importer function) and a typo in either
    should read as a named error, not an opaque one.
    """
    try:
        return source.url_pattern.format(**fields)
    except KeyError as exc:
        raise AnnotationSourcesError(
            f"source {source.id!r} url_pattern {source.url_pattern!r} needs field {exc}, "
            f"which was not provided (got {sorted(fields)})"
        ) from exc


# ---------------------------------------------------------------------------------------------
# GO evidence codes -> this project's evidence/confidence model
#
# Categories per the Gene Ontology Consortium's own published evidence code groupings
# (https://geneontology.org/docs/guide-go-evidence-codes/ -- read from background knowledge in
# this session, not fetched live; unverified). Two codes are pulled out of their category's
# default because the category label alone overstates them:
#   NAS ("Non-traceable Author Statement") is an author's claim with no citable source, weaker
#       than TAS ("Traceable Author Statement") even though GO files both as 'author_statement'.
#   ND ("No biological Data available") records the *absence* of a known function, not a positive
#       claim about one -- 'unverified' is the honest confidence for a row built from it.
# ---------------------------------------------------------------------------------------------

#: code -> category. Every GO evidence code in current use should appear here; an unrecognized
#: code is a data problem worth surfacing (`UnknownGoEvidenceCodeError`), not something to guess.
GO_EVIDENCE_CATEGORIES: Final[dict[str, str]] = {
    # Experimental: a specific assay was performed.
    "EXP": "experimental",
    "IDA": "experimental",
    "IPI": "experimental",
    "IMP": "experimental",
    "IGI": "experimental",
    "IEP": "experimental",
    "HTP": "experimental",
    "HDA": "experimental",
    "HMP": "experimental",
    "HGI": "experimental",
    "HEP": "experimental",
    # Phylogenetically inferred.
    "IBA": "phylogenetic",
    "IBD": "phylogenetic",
    "IKR": "phylogenetic",
    "IRD": "phylogenetic",
    # Computational analysis, including plain electronic annotation (IEA).
    "ISS": "computational",
    "ISO": "computational",
    "ISA": "computational",
    "ISM": "computational",
    "IGC": "computational",
    "RCA": "computational",
    "IEA": "computational",
    # Author statement.
    "TAS": "author_statement",
    "NAS": "author_statement",
    # Curator statement.
    "IC": "curator_statement",
    "ND": "curator_statement",
}

_CONFIDENCE_BY_CATEGORY: Final[dict[str, str]] = {
    "experimental": "high",
    "phylogenetic": "medium",
    "computational": "low",
    "author_statement": "medium",  # TAS's default; NAS is overridden below
    "curator_statement": "medium",  # IC's default; ND is overridden below
}

#: Per-code overrides where the category default would overstate this specific code (see the
#: section docstring above for NAS and ND).
_CONFIDENCE_OVERRIDE_BY_CODE: Final[dict[str, str]] = {
    "NAS": "low",
    "ND": "unverified",
}


class UnknownGoEvidenceCodeError(ValueError):
    """A GO evidence code this module does not recognize.

    Raised rather than guessing a category: an unrecognized code (a typo, or a code the GO
    Consortium has since retired or added) must surface as a named gap, not silently fall back to
    some default confidence.
    """


def go_evidence_category(code: str) -> str:
    """One of 'experimental' | 'phylogenetic' | 'computational' | 'author_statement' |
    'curator_statement', per the GO Consortium's own evidence code groupings."""
    normalized = code.strip().upper()
    try:
        return GO_EVIDENCE_CATEGORIES[normalized]
    except KeyError as exc:
        raise UnknownGoEvidenceCodeError(f"unrecognized GO evidence code: {code!r}") from exc


def recommended_confidence_for_go_evidence(code: str) -> str:
    """The editorial-default `confidence` (docs/reference/CONVENTIONS.md's closed set) for a
    `gene_annotation` row built from GO evidence code `code`.

    A DEFAULT, not a verified fact: this is this implementation's policy read of how much each GO
    evidence category deserves to be trusted, not something checked against a source for any
    specific gene. An importer uses it when writing a fresh row; a curator reviewing that row is
    always free to override `confidence` up or down. `evidence_code` itself is always carried
    through onto the row unchanged (see this module's docstring) so that override decision has
    something honest to look at.
    """
    normalized = code.strip().upper()
    category = go_evidence_category(normalized)  # validates and raises on an unknown code
    if normalized in _CONFIDENCE_OVERRIDE_BY_CODE:
        return _CONFIDENCE_OVERRIDE_BY_CODE[normalized]
    return _CONFIDENCE_BY_CATEGORY[category]
