"""The RO-Crate metadata descriptor, and an honest account of how much of the spec it is.

RO-Crate is JSON-LD with a prescribed shape: a file called `ro-crate-metadata.json` holding an
`@context` and an `@graph`, in which one entity describes the file itself (`conformsTo` the
RO-Crate profile, `about` the root) and one entity with `@id "./"` is the root data entity -- a
`Dataset` whose `hasPart` reaches every file the crate describes.

**This module writes that shape by hand and claims nothing beyond it.** PLAN.md's hard constraint
for this work was no new dependency, so there is no `rocrate` library here and, equally, no
validator: nothing checked this output against the specification except a reading of it. Writing
`conformsTo: https://w3id.org/ro/crate/1.1` is a claim, and a claim nobody verified is exactly
what `docs/reference/CONVENTIONS.md` means by "never write high confidence from memory". So the
claim is made narrowly and the limits are published *in the bundle itself*, as
:data:`CRATE_SPEC_IMPLEMENTED` and :data:`CRATE_SPEC_NOT_IMPLEMENTED`, which `manifest.json`
carries verbatim. A consumer who needs strict conformance can read those two lists before
trusting the descriptor, instead of discovering the gaps by running a validator on it.

**The one design decision worth defending: no custom context terms.** The zone of a row, its
evidence level and its three-state absences are the most important things in this bundle, and it
is tempting to express them as RO-Crate properties -- `fermdb:zone` and so on. That requires
extending `@context` with a namespace URI, and any URI this project minted today would resolve to
nothing. An unresolvable term in a JSON-LD context is silently dropped by a conforming processor,
which would mean the zone label survives in the crate for a human reader and vanishes for a
machine one. That is the worst of both. So the crate uses only schema.org terms that the RO-Crate
1.1 context already defines, each Zone I file's `description` says in words that it is inference,
and the machine-readable zone lives where it cannot be dropped: on every row of the data, and in
`manifest.json`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:  # pragma: no cover - import for types only, and release.py imports this module
    from .release import FileRecord

__all__ = [
    "CRATE_PROFILE",
    "CRATE_SPEC_IMPLEMENTED",
    "CRATE_SPEC_NOT_IMPLEMENTED",
    "build_crate",
]

#: The RO-Crate version this descriptor is written against.
CRATE_PROFILE: Final[str] = "https://w3id.org/ro/crate/1.1"

_CONTEXT: Final[str] = "https://w3id.org/ro/crate/1.1/context"

#: What of RO-Crate 1.1 this module actually emits. Copied into `manifest.json` so the bundle
#: carries its own account of itself rather than relying on a reader finding this file.
CRATE_SPEC_IMPLEMENTED: Final[tuple[str, ...]] = (
    "the file is named ro-crate-metadata.json and sits at the root of the crate directory",
    f"@context is the RO-Crate 1.1 context ({_CONTEXT})",
    "a metadata descriptor entity of @type CreativeWork, @id 'ro-crate-metadata.json', with "
    f"conformsTo {CRATE_PROFILE} and about pointing at the root data entity",
    "a root data entity with @id './', @type Dataset, and the four properties RO-Crate requires "
    "of it: name, description, datePublished and license",
    "a File data entity for every file in the bundle, with name, description, encodingFormat and "
    "contentSize",
    "a Dataset data entity for every directory, with hasPart reaching its immediate children, so "
    "hasPart from the root reaches every file transitively",
    "license as a contextual entity (a CreativeWork) rather than a URL, because the repository "
    "declares no licence URL and inventing one would be worse than describing the situation",
    "identifier on the root as urn:sha256:<bundle digest>, which names this exact state of the "
    "atlas (PLAN.md T.2, T.5)",
)

#: What it does not. Published for the same reason: a conformance claim nobody checked is a lie
#: with good intentions.
CRATE_SPEC_NOT_IMPLEMENTED: Final[tuple[str, ...]] = (
    "NOT VALIDATED: no RO-Crate validator or library was run against this output (no new "
    "dependency was permitted for this work, and the build has no network). The shape is written "
    "from a reading of the specification, not verified against it.",
    "no ro-crate-preview.html and no ro-crate-preview_files/ -- RO-Crate recommends a human "
    "readable rendering of the crate and this bundle ships README.md instead",
    "no Workflow Run Crate / Process Run Crate profile: `processing_run` rows are exported as "
    "data and as provenance/processing_runs.jsonl, NOT modelled in the crate graph as "
    "CreateAction / SoftwareApplication / SoftwareSourceCode entities with object and result",
    "no Provenance Run Crate linking each analysis_result entity to the run that produced it in "
    "the graph; that graph is in provenance/, not in @graph",
    "no contextual entities for people or organisations: the atlas records curator names as "
    "strings on rows and holds no ORCIDs or affiliations, so author on the root is omitted "
    "rather than fabricated",
    "no custom @context terms, so zone, evidence level and the three-state absences appear in "
    "the crate only inside human-readable descriptions -- machine-readably they live on every "
    "data row and in manifest.json (see this module's docstring for why)",
    "no sha256 on the File entities: RO-Crate 1.1's base context defines no checksum property, "
    "and the per-file hashes are in manifest.json instead",
    "no zipped/packaged crate and no absolute @id URIs: this is a directory crate with relative "
    "identifiers",
    "no conformsTo on the root data entity naming a further profile, because it conforms to none",
)


#: What each directory in the bundle is, for the crate's Dataset entities. A directory the export
#: did not write gets a neutral description rather than a guess.
_DIRECTORY_DESCRIPTIONS: Final[Mapping[str, str]] = {
    "data": "The fact tables, one JSONL file per table per zone. No file holds two zones.",
    "data/reported": (
        "Zone R -- REPORTED. Exactly as the source stated it. May support a conclusion."
    ),
    "data/harmonized": (
        "Zone H -- HARMONIZED. Derived from Zone R by recorded code and reconstructible from it. "
        "May support a conclusion."
    ),
    "data/inferred": (
        "Zone I -- INFERRED. Statistical, model or LLM output. THIS IS NOT REPORTED CONTENT and "
        "may NOT support a conclusion until a curator has promoted it. Every row inside carries "
        '"_is_inference": true and "_may_support_a_conclusion": false.'
    ),
    "data/unzoned": (
        "Tables carrying no zone column: controlled vocabularies, join tables, and the record "
        "that a computation happened. Not claims about biology."
    ),
    "data/zone-unrecognised": (
        "Rows whose stored zone is not one of R/H/I, which a CHECK constraint should have "
        "prevented. Treated as inference, never as reported, and named in manifest.json."
    ),
    "schema": "The DDL the export was taken at, and the column shape of every exported table.",
    "provenance": (
        "The provenance graph: evidence chains from assertion to the measurement or publication "
        "it rests on, the recipe of every computed result, the versions, and the licence terms."
    ),
}


def _directories(paths: Sequence[str]) -> dict[str, list[str]]:
    """Map every directory in the bundle (plus the root, as '') to its immediate children."""
    children: dict[str, set[str]] = {"": set()}
    for path in paths:
        parts = path.split("/")
        for depth in range(len(parts)):
            parent = "/".join(parts[:depth])
            child = "/".join(parts[: depth + 1])
            children.setdefault(parent, set()).add(child)
    return {parent: sorted(kids) for parent, kids in children.items()}


def _entity_id(path: str, directories: Mapping[str, list[str]]) -> str:
    """RO-Crate identifies a directory with a trailing slash and a file without one."""
    return f"{path}/" if path in directories else path


def _directory_description(path: str) -> str:
    return _DIRECTORY_DESCRIPTIONS.get(
        path, f"Files under {path}/. See manifest.json for what each one holds."
    )


def build_crate(
    *,
    records: Sequence[FileRecord],
    generated_at: str,
    release: str | None,
    digest: str,
    n_inferred: int,
) -> dict[str, Any]:
    """Build the `ro-crate-metadata.json` payload describing `records`.

    Args:
        records: Every file already written into the bundle. The descriptor itself is not among
            them and is not part of the crate's `hasPart` -- in RO-Crate it describes the crate
            rather than belonging to it.
        generated_at: ISO 8601 UTC, used as the root's `datePublished`.
        release: PLAN.md T.4's `vYYYY.N`, if this bundle is one. Becomes the root's `version`;
            omitted entirely when there is none, rather than filled in with the date.
        digest: The bundle digest, which becomes the root's `identifier` as a `urn:sha256:` URN.
        n_inferred: How many Zone I rows the bundle holds, stated in the root description so that
            the first sentence a reader of the crate meets says whether there is inference in it.
    """
    paths = sorted(record.path for record in records)
    directories = _directories(paths)
    by_path = {record.path: record for record in records}

    graph: list[dict[str, Any]] = [
        {
            "@id": "ro-crate-metadata.json",
            "@type": "CreativeWork",
            "conformsTo": {"@id": CRATE_PROFILE},
            "about": {"@id": "./"},
            "description": (
                "RO-Crate metadata descriptor. manifest.json records exactly which parts of the "
                "RO-Crate specification this descriptor implements and which it does not."
            ),
        }
    ]

    root: dict[str, Any] = {
        "@id": "./",
        "@type": "Dataset",
        "name": "fermdb release export" + (f" {release}" if release else " (unversioned snapshot)"),
        "description": (
            "An export of the fermdb isobutanol strain-engineering atlas (PLAN.md T.5): the fact "
            "tables, the schema they were taken at, the provenance graph behind every assertion, "
            "the pipeline and tool versions, and the licence terms per source. "
            f"It holds {n_inferred} INFERRED (Zone I) row(s), exported in data/inferred/ and "
            "labelled row by row: Zone I is model, statistical or LLM output and may not support "
            "a conclusion until a curator has promoted it. Zone R (reported) and Zone H "
            "(harmonized) are in separate files and no file mixes two zones. Read manifest.json "
            "before the data: it carries the zone, evidence-level and missing-value rules as "
            "machine-readable data, and names every row this export could not read cleanly."
        ),
        "datePublished": generated_at,
        "identifier": f"urn:sha256:{digest}",
        "license": {"@id": "#bundle-licence"},
        "hasPart": [{"@id": _entity_id(child, directories)} for child in directories.get("", [])],
    }
    if release:
        root["version"] = release
    graph.append(root)

    graph.append(
        {
            "@id": "#bundle-licence",
            "@type": "CreativeWork",
            "name": "See provenance/licences.json",
            "description": (
                "The terms of this bundle are not a single licence. provenance/licences.json "
                "records what the repository itself declares (which may be nothing -- in which "
                "case this export says so rather than assuming permissive terms), the licence "
                "and redistributability of every external annotation database the atlas imports "
                "from, and the access terms recorded per publication and per deposit. "
                "span.quoted_text holds verbatim sentences from the cited publications, so "
                "redistribution is governed by their terms as well."
            ),
        }
    )

    for path in sorted(directories):
        if path == "":
            continue
        graph.append(
            {
                "@id": f"{path}/",
                "@type": "Dataset",
                "name": path.split("/")[-1],
                "description": _directory_description(path),
                "hasPart": [{"@id": _entity_id(child, directories)} for child in directories[path]],
            }
        )

    for path in paths:
        record = by_path[path]
        graph.append(
            {
                "@id": path,
                "@type": "File",
                "name": path.split("/")[-1],
                "description": record.description,
                "encodingFormat": record.media_type,
                "contentSize": str(record.size_bytes),
            }
        )

    return {"@context": _CONTEXT, "@graph": graph}
