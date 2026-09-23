"""The typed payload one publication's extraction produces, and the JSON Schema that holds it.

PLAN.md H.5 names seven things an extraction must be able to say about a paper — strains,
modifications, pathway configurations, measurements, conditions, bottlenecks, and the higher
alcohols co-reported alongside isobutanol. An eighth was added: ``part_expression_records``, for
PLAN.md G.6's *"one row per demonstrated host/compartment combination"*. It is not an H.5 kind and
is not pretending to be one — it exists because `part` had 16 rows and `part_expression_record`
had none, and G.6 is explicit that the expression records are **"the field that makes the catalog
worth having"**: without them the catalog can say an enzyme exists and not whether anyone has ever
got it to work anywhere. Nothing could propose one while this module had no such section, so the
gap was not a curation backlog; it was unreachable. This module is the single definition of all
eight, in three synchronized forms:

* a :class:`SectionSpec` per payload section, which is the authority;
* a JSON Schema generated from those specs, used twice — as a decoding constraint for a backend
  that supports one, and (always) as :func:`fermdb.llm.validate.check_json_schema`'s input, because
  a provider's promise to honour a schema is not a validation;
* a frozen dataclass per record, so the rest of fermdb reads an extraction through attributes
  rather than by indexing a dict with string keys and hoping.

Three rules shape every field below.

**No vocabulary is written in this file.** Product ids, units, bases, modification types,
compartments, compartment strategies and condition facets are all read from
``data/vocabularies/*.tsv`` and from the ``compartment_strategy`` table, and turned into ``enum``
constraints at schema-build time. That is CONVENTIONS.md's "no ``if product == 'ethanol'``" applied
one level earlier: if a vocabulary value appeared here, adding a product would mean editing code.

**The model selects; it does not mint.** PLAN.md L.1.2 — wherever the atlas can enumerate the
possibilities, the agent picks among them. So the model never invents a product identifier; it
chooses one from the enum or says ``'unknown'``. An id it cannot choose is not silently mapped to
the nearest plausible one, and ``'unknown'`` is a real answer with its own meaning, distinct from
omitting the field.

**No record has a ``confidence`` field**, and every record schema sets
``additionalProperties: false``, so a model cannot supply one even by trying. MODEL_ROUTING.md §5.2
forbids model capability or self-report from entering the derivation of a confidence value;
:func:`fermdb.llm.validate.validate_records` forces ``'unverified'`` onto everything regardless,
and this makes the attempt unrepresentable rather than merely overridden. The payload's one
``self_confidence`` field is the audit trail, and nothing reads it.

**Everything reported is shadowed as reported.** Every field the model has to interpret carries an
``*_as_reported`` sibling holding the paper's own wording, because the interpretation is Zone I and
rebuildable while the paper's words are not.

Every record additionally requires a ``span``: a verbatim quote plus 0-based half-open character
offsets. PLAN.md H.5 is flat about it — *no extracted value is storable without a span* — and
:func:`fermdb.llm.validate.verify_span` re-reads the source at those offsets. This module's job is
to make a span structurally unskippable; that module's job is to make it true.
"""

from __future__ import annotations

import csv
import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from ..config import Settings
from ..llm.validate import load_units

__all__ = [
    "MISSING_CHOICES",
    "RECORD_KINDS",
    "SPAN_SCHEMA",
    "BottleneckRecord",
    "ConditionRecord",
    "ExtractedSpan",
    "FieldSpec",
    "MeasurementRecord",
    "ModificationRecord",
    "PartExpressionRecord",
    "PathwayConfigurationRecord",
    "PayloadVocabulary",
    "SchemaBuildError",
    "SectionSpec",
    "StrainRecord",
    "iter_payload_records",
    "load_vocabulary",
    "payload_schema",
    "payload_sections",
    "record_path",
    "section_for",
]

JsonObject = dict[str, Any]
JsonSchema = dict[str, Any]


class SchemaBuildError(RuntimeError):
    """A payload schema could not be built — usually an empty vocabulary.

    Raised rather than falling back to a free-text field: an ``enum`` that quietly became "any
    string" would let a model invent product ids, and the failure would only surface much later as
    an unresolvable identifier.
    """


#: Added to every controlled-value enum. CONVENTIONS.md, "Missing values": ``'NA'`` (recorded as
#: not applicable) and ``'unknown'`` (recorded, could not be resolved) are two different answers,
#: and both differ from omitting the field, which means the source never said. A model that can
#: only choose from real values will choose a wrong real value.
MISSING_CHOICES: Final[tuple[str, str]] = ("NA", "unknown")

#: A verbatim quote and where it sits in the text the model was shown. Mirrors
#: :class:`fermdb.llm.validate.Span`, whose ``from_mapping`` reads exactly these keys.
SPAN_SCHEMA: Final[JsonSchema] = {
    "type": "object",
    "description": (
        "Where this record's evidence is in the text you were given. 'quote' must be copied "
        "character for character; char_start/char_end are 0-based and half-open, so "
        "text[char_start:char_end] == quote exactly."
    ),
    "required": ["quote", "char_start", "char_end"],
    "properties": {
        "quote": {"type": "string", "minLength": 1, "maxLength": 600},
        "char_start": {"type": "integer", "minimum": 0},
        "char_end": {"type": "integer", "minimum": 1},
        "section": {"type": ["string", "null"]},
    },
    "additionalProperties": False,
}

#: A hard ceiling per section. Not a guess about how much a paper contains: a model that starts
#: repeating itself produces hundreds of near-identical records, and a run that returns 5000 rows
#: has failed in a way worth catching at the schema rather than in the curation queue.
MAX_RECORDS_PER_SECTION: Final[int] = 200


# -------------------------------------------------------------------------------- vocabularies


def _read_tsv_column(path: Path, column: str) -> tuple[str, ...]:
    """The distinct values of one column of a commented vocabulary TSV, in file order.

    Its own small reader rather than pandas, for the reason ``tests/test_vocabularies.py`` gives:
    pandas reads the literal string ``'NA'`` as a missing value and collapses two of this
    project's three missing states into one.
    """
    if not path.is_file():
        raise SchemaBuildError(f"vocabulary file not found: {path}")
    with path.open(encoding="utf-8") as handle:
        lines = [line for line in handle if not line.lstrip().startswith("#") and line.strip()]
    seen: list[str] = []
    for row in csv.DictReader(lines, delimiter="\t"):
        value = (row.get(column) or "").strip()
        if value and value not in seen:
            seen.append(value)
    if not seen:
        raise SchemaBuildError(f"{path} has no values in column {column!r}")
    return tuple(seen)


@dataclass(frozen=True)
class PayloadVocabulary:
    """Every closed value set the payload schema needs, loaded from data rather than written here.

    Built by :func:`load_vocabulary`. Constructed directly only in tests, which is also the reason
    it is a plain frozen dataclass rather than something that reads files in ``__init__``.
    """

    product_ids: tuple[str, ...]
    units: tuple[str, ...]
    bases: tuple[str, ...]
    modification_types: tuple[str, ...]
    quantity_kinds: tuple[str, ...]
    compartments: tuple[str, ...]
    compartment_strategies: tuple[str, ...]
    condition_facets: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in (
            "product_ids",
            "units",
            "bases",
            "modification_types",
            "quantity_kinds",
            "compartments",
            "compartment_strategies",
            "condition_facets",
        ):
            if not getattr(self, name):
                raise SchemaBuildError(
                    f"{name} is empty, so its schema enum would have to be widened to 'any "
                    f"string' — which is how a model ends up inventing one. Load the vocabulary "
                    f"first."
                )


def load_vocabulary(source: Settings | Path, conn: sqlite3.Connection) -> PayloadVocabulary:
    """Read every closed value set from ``data/vocabularies`` and from the database.

    ``compartment_strategies`` comes from the ``compartment_strategy`` table rather than a TSV
    because that is where it lives (schema.sql seeds it from ISOBUTANOL_PROGRAM.md section 2 and
    MITOCHONDRIAL_PROGRAM.md section 4); the rest come from the repo-tier vocabularies.
    """
    directory = source if isinstance(source, Path) else source.path("vocabularies_dir")
    units_table = load_units(directory)
    strategies = tuple(
        str(row[0]) for row in conn.execute("SELECT id FROM compartment_strategy ORDER BY id")
    )
    if not strategies:
        raise SchemaBuildError(
            "the compartment_strategy table is empty; schema.sql seeds it, so an empty table "
            "means this database was not created by create_schema()"
        )
    return PayloadVocabulary(
        product_ids=_read_tsv_column(directory / "products.tsv", "id"),
        units=tuple(sorted(units_table.units)),
        bases=tuple(sorted(units_table.bases)),
        modification_types=_read_tsv_column(
            directory / "modification_types.tsv", "modification_type"
        ),
        quantity_kinds=_read_tsv_column(directory / "quantity_kinds.tsv", "quantity_kind"),
        compartments=_read_tsv_column(directory / "compartments.tsv", "compartment"),
        compartment_strategies=strategies,
        condition_facets=_read_tsv_column(directory / "condition_facets.tsv", "field"),
    )


def _choice(values: Sequence[str], *, description: str, nullable: bool = False) -> JsonSchema:
    """An enum over a vocabulary plus the two recorded-missing answers."""
    allowed: list[Any] = [*values, *MISSING_CHOICES]
    if nullable:
        allowed.append(None)
    return {
        "type": ["string", "null"] if nullable else "string",
        "enum": allowed,
        "description": description,
    }


def _text(description: str, *, nullable: bool = False, maximum: int = 400) -> JsonSchema:
    if nullable:
        return {"type": ["string", "null"], "maxLength": maximum, "description": description}
    return {"type": "string", "minLength": 1, "maxLength": maximum, "description": description}


def _number(description: str, *, nullable: bool = False) -> JsonSchema:
    return {
        "type": ["number", "null"] if nullable else "number",
        "description": description,
    }


# ------------------------------------------------------------------------------- section specs


@dataclass(frozen=True)
class FieldSpec:
    """One field of one record: its name, its JSON Schema fragment, and whether it is required."""

    name: str
    schema: JsonSchema
    required: bool = False


@dataclass(frozen=True)
class SectionSpec:
    """One array in the payload — ``measurements``, ``strains``, and so on."""

    key: str
    title: str
    guidance: str
    fields: tuple[FieldSpec, ...]

    @property
    def field_names(self) -> tuple[str, ...]:
        """Every field name including ``span``, in declaration order."""
        return (*(field.name for field in self.fields), "span")

    def record_schema(self) -> JsonSchema:
        """The JSON Schema for one record of this section."""
        properties: JsonSchema = {field.name: field.schema for field in self.fields}
        properties["span"] = SPAN_SCHEMA
        return {
            "type": "object",
            "description": self.guidance,
            # `span` is required on every record, without exception. PLAN.md H.5.
            "required": [*(f.name for f in self.fields if f.required), "span"],
            "properties": properties,
            "additionalProperties": False,
        }

    def array_schema(self) -> JsonSchema:
        """The schema for the whole array, empty list included."""
        return {
            "type": "array",
            "title": self.title,
            "description": self.guidance,
            "items": self.record_schema(),
            "maxItems": MAX_RECORDS_PER_SECTION,
        }


def _strain_fields() -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "name_as_reported",
            _text("The strain's name exactly as the paper writes it, e.g. 'CEN.PK113-7D'."),
            required=True,
        ),
        FieldSpec(
            "role",
            _choice(
                ("engineered", "parent", "control", "wild_type"),
                description=(
                    "What the strain is FOR in this experiment. 'unknown' if the paper names it "
                    "without saying."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "parent_name_as_reported",
            _text("The parent strain's name as written, if the paper states one.", nullable=True),
        ),
        FieldSpec(
            "background_as_reported",
            _text("The genetic background as written, if stated separately.", nullable=True),
        ),
        # Added after a real extraction dropped it. Wess et al. list 17 strains with full
        # genotypes in a table; the section had nowhere to put them, so the atlas kept the names
        # and lost "Δilv2; Δbdh1; Δbdh2; Δleu4; Δleu9; Δecm31; Δilv1; Δadh1; Δgpd1; Δgpd2".
        #
        # The `genotype` table has held `as_reported` (Zone R) beside `parsed_json` (Zone H)
        # since the schema was written, which is exactly this shape: keep the paper's string
        # untouched, and derive structure from it by recorded code rather than by asking a model
        # to decompose it. `curate.genotype` does the deriving.
        FieldSpec(
            "genotype_as_reported",
            _text(
                "The full genotype string exactly as the paper writes it, e.g. "
                "'Δilv2; Δbdh1; Δbdh2' or 'BY4741/pATP426-kivd-ADH6'. Copy it verbatim "
                "including the delta characters and separators; do not expand, reorder or "
                "normalise it, and do not assemble one from prose if the paper gives none.",
                nullable=True,
            ),
        ),
    )


def _modification_fields(vocabulary: PayloadVocabulary) -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "target_as_reported",
            _text("The gene, protein or locus changed, exactly as the paper names it."),
            required=True,
        ),
        FieldSpec(
            "modification_type",
            _choice(
                vocabulary.modification_types,
                description="Choose from the list. Do not invent a category.",
            ),
            required=True,
        ),
        FieldSpec(
            "strain_name_as_reported",
            _text("Which strain carries this change, as written.", nullable=True),
        ),
        FieldSpec(
            "compartment",
            _choice(
                vocabulary.compartments,
                description="Where the product ends up, if the paper says.",
                nullable=True,
            ),
        ),
        FieldSpec(
            "encoding_genome",
            _choice(
                ("nuclear", "mitochondrial"),
                description=(
                    "Which genome physically carries the gene. This decides the genetic code and "
                    "is NOT the same as the compartment: a nuclear gene whose product is imported "
                    "into the matrix is still 'nuclear'. Answer 'unknown' unless the paper is "
                    "explicit."
                ),
                nullable=True,
            ),
        ),
        FieldSpec(
            "detail_as_reported",
            _text("The paper's own description of the change.", nullable=True),
        ),
    )


def _pathway_configuration_fields(vocabulary: PayloadVocabulary) -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "compartment_strategy",
            _choice(
                vocabulary.compartment_strategies,
                description=(
                    "Which of the atlas's compartmentalization strategies this build is. "
                    "'unknown' if the paper does not make it clear."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "strain_name_as_reported",
            _text("Which strain this configuration belongs to, as written.", nullable=True),
        ),
        FieldSpec(
            "enzymes_as_reported",
            {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 200},
                "maxItems": 40,
                "description": "The pathway enzymes the paper names, in its own words.",
            },
        ),
        FieldSpec(
            "localization_as_reported",
            _text("How the paper describes where the enzymes were put.", nullable=True),
        ),
        FieldSpec(
            "cofactor_note_as_reported",
            _text(
                "Anything the paper says about NADH/NADPH balance for this build.", nullable=True
            ),
        ),
    )


def _measurement_fields(vocabulary: PayloadVocabulary) -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "product_id",
            _choice(
                vocabulary.product_ids,
                description=(
                    "Pick the atlas id for the measured product. If the product is not in the "
                    "list, answer 'unknown' — never the closest-looking id."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "product_as_reported",
            _text("The product's name exactly as the paper writes it."),
            required=True,
        ),
        FieldSpec(
            "quantity_kind",
            # Was free prose with a trailing "...", and the "..." is where 17 of the atlas's 21
            # stored values came from -- whole sentences like "isobutanol concentration on SC
            # agar permitting growth". A closed choice with an explicit escape is the same shape
            # `unit` already uses, and for the same reason: an open field does not get answered
            # more accurately, it gets answered in prose.
            _choice(
                vocabulary.quantity_kinds,
                description=(
                    "What was measured, chosen from the list. A relative measurement "
                    "(fold_change, percent_change) is only usable if the control it was computed "
                    "against is named in the record, so say which control it was. If the paper's "
                    "quantity is not in the list, answer 'unknown' rather than describing it in "
                    "a sentence -- a sentence in this field cannot be grouped or compared."
                ),
            ),
            required=True,
        ),
        FieldSpec("value", _number("The number as printed. Do not convert it."), required=True),
        FieldSpec(
            "unit",
            _choice(
                vocabulary.units,
                description=(
                    "The unit as printed, chosen from the list. If the paper's unit is not in the "
                    "list, answer 'unknown' rather than converting into one that is."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "basis",
            _choice(
                vocabulary.bases,
                description=(
                    "Mandatory for a yield: g/g-consumed and g/g-supplied are different numbers "
                    "and papers report both without saying which. 'unknown' when the paper does "
                    "not state it."
                ),
                nullable=True,
            ),
        ),
        FieldSpec(
            "substrate",
            _text("The substrate a yield is per, e.g. 'glucose'.", nullable=True),
        ),
        FieldSpec(
            "strain_name_as_reported",
            _text("Which strain this number belongs to, as written.", nullable=True),
        ),
        FieldSpec("time_h", _number("Hours into the fermentation, if stated.", nullable=True)),
        FieldSpec(
            "source_locator",
            _text("Where in the paper: 'table 2', 'figure 4B', 'text'."),
            required=True,
        ),
        FieldSpec(
            "is_digitized",
            {
                "type": "boolean",
                "description": (
                    "True if the number was read off a figure rather than printed. A digitized "
                    "value is a different grade of evidence from a tabulated one."
                ),
            },
        ),
        # The `measurement` table has carried is_upper_bound and is_below_lod since the schema was
        # written, but the extraction payload had no way to set either -- so a paper saying
        # "not exceeding 6.4 mg/L" or "below the limit of quantification" could only be recorded
        # as a plain value, asserting an equality the paper does not claim. Found on the third
        # real extraction (10.1016/j.btre.2026.e00959).
        FieldSpec(
            "is_upper_bound",
            {
                "type": "boolean",
                "description": (
                    "True when the paper states a ceiling rather than a value -- 'not exceeding "
                    "6.4 mg/L', '<0.1 g/L'. The number is then the bound, not the measurement, "
                    "and a comparison that treats it as a measurement overstates the strain."
                ),
            },
        ),
        FieldSpec(
            "is_below_lod",
            {
                "type": "boolean",
                "description": (
                    "True when the paper reports the value as below its detection or "
                    "quantification limit. Distinct from zero and from absent: the assay ran and "
                    "could not see it, which is evidence, where a missing number is not."
                ),
            },
        ),
    )


def _condition_fields(vocabulary: PayloadVocabulary) -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "facet",
            _choice(
                vocabulary.condition_facets,
                description="Which fermentation-condition facet this is, from the list.",
            ),
            required=True,
        ),
        FieldSpec(
            "value_as_reported",
            _text("The paper's own string: '30 +/- 1 C', 'micro-aerobic (0.2 vvm)', 'YPD'."),
            required=True,
        ),
        FieldSpec(
            "strain_name_as_reported",
            _text("Which strain or run this condition applies to, as written.", nullable=True),
        ),
    )


def _bottleneck_fields() -> tuple[FieldSpec, ...]:
    return (
        FieldSpec(
            "node_as_reported",
            _text("The step, enzyme, metabolite or pool said to be limiting, as written."),
            required=True,
        ),
        FieldSpec(
            "claim",
            _text("What is claimed about it, in one sentence.", maximum=600),
            required=True,
        ),
        FieldSpec(
            "support",
            _choice(
                ("stated_by_authors", "inferred_from_data"),
                description=(
                    "Did the authors say this, or is it your reading of their data? These are "
                    "different claims and the atlas stores them differently."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "intervention_as_reported",
            _text("What, if anything, they did about it, and whether it helped.", nullable=True),
        ),
    )


def _part_expression_fields(vocabulary: PayloadVocabulary) -> tuple[FieldSpec, ...]:
    """One demonstrated host × compartment for one part, per PLAN.md G.6.

    The fields are G.6's own list — ``{host, compartment, codon_optimized, promoter,
    expressed_ok, activity_measured, outcome_measurement_id}`` — minus the one a model cannot
    supply and plus the two shadows this module's rules require.

    ``outcome_measurement_id`` is **absent on purpose**. It is a foreign key into `measurement`,
    and a row id is not something that can be read out of a paper; the same sentence that reports
    the outcome is already a `measurements` proposal, and asking the model to also name the row it
    will become would be asking it to mint an identifier. `curate.promote` takes it from a curator
    instead. ``outcome_as_reported`` is what the paper actually says about how it went, which is a
    different thing and is storable from the text alone.

    ``part_as_reported`` is free text rather than a choice over the `part` table, which is the one
    real judgement call here. The alternative — loading the 16 catalog ids into
    :class:`PayloadVocabulary` beside ``compartment_strategies`` and having the model select one —
    was rejected twice over. First, `part` is *curated data that grows*, not a seeded vocabulary:
    `compartment_strategy` is seeded by schema.sql and is the same on every machine, while `part`
    is empty until `fermdb atlas pathways` runs, so the schema would refuse to build on a database
    that is otherwise perfectly able to extract. Second, every identity claim in that catalog is
    Zone I and `unverified`, and it covers only the isobutanol step roles; a model shown 16 ids
    and a paper about a 17th enzyme is being invited to pick the closest-looking one, which is the
    resolution error CONVENTIONS.md's identifier rules forbid by name. Mapping the paper's words
    onto a catalog part is a curator's act, and `curate.promote` refuses until one does it.
    """
    return (
        FieldSpec(
            "part_as_reported",
            _text(
                "The enzyme, gene or construct that was expressed, exactly as the paper names it "
                "-- 'alsS from Bacillus subtilis', 'kivd', 'Ll-KivD'. One part per record: a "
                "paper expressing alsS, ilvC and ilvD in the same host gives three records, not "
                "one naming three."
            ),
            required=True,
        ),
        FieldSpec(
            "host_as_reported",
            _text(
                "The organism or strain it was expressed IN, as written -- 'E. coli BL21(DE3)', "
                "'S. cerevisiae CEN.PK113-5D'. 'Worked in E. coli' and 'works in the yeast "
                "mitochondrial matrix' are different facts, so a record with no host states "
                "nothing. Where the paper names only a species, copy the species."
            ),
            required=True,
        ),
        FieldSpec(
            "compartment",
            _choice(
                vocabulary.compartments,
                description=(
                    "Where in the cell the part was expressed or shown to act, from the list. "
                    "Answer 'unknown' unless the paper localizes it -- do not fill this in from "
                    "where the enzyme normally lives, because relocalizing it is often the whole "
                    "experiment."
                ),
                nullable=True,
            ),
        ),
        FieldSpec(
            "compartment_as_reported",
            _text(
                "The paper's own words for where it was put -- 'targeted to the mitochondrial "
                "matrix with the Su9 presequence', 'cytosolic'. Kept even when the field above "
                "resolved, because the targeting method is in this string and nowhere else.",
                nullable=True,
            ),
        ),
        FieldSpec(
            "encoding_genome",
            _choice(
                ("nuclear", "mitochondrial"),
                description=(
                    "Which genome physically carried the gene in THIS experiment. Not the "
                    "compartment: a nuclear gene whose product is imported into the matrix is "
                    "'nuclear'. It decides the genetic code, and so it also decides what "
                    "'codon optimized' below can possibly mean -- optimized for which code? "
                    "Answer 'unknown' unless the paper is explicit."
                ),
                nullable=True,
            ),
        ),
        FieldSpec(
            "codon_optimized",
            _choice(
                ("yes", "no"),
                description=(
                    "Did they codon-optimize the sequence for the host? 'yes' or 'no' only where "
                    "the paper says so; omit the field entirely if it never mentions it. 'The "
                    "paper did not say' and 'the paper says they did not' are different answers "
                    "and the atlas stores them differently."
                ),
                nullable=True,
            ),
        ),
        FieldSpec(
            "promoter_as_reported",
            _text(
                "What drove expression, as written -- 'TDH3', 'pGAL1', 'T7'. Free text, because "
                "this is a promoter name from the paper and not a controlled value.",
                nullable=True,
            ),
        ),
        FieldSpec(
            "expressed_ok",
            _choice(
                ("yes", "no", "partial"),
                description=(
                    "Did the protein actually appear? 'partial' covers a low, truncated, "
                    "insoluble or partly-processed product the paper reports as such. 'unknown' "
                    "if they expressed it and never say whether it worked -- which is common, "
                    "and is a real answer here."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "activity_measured",
            _choice(
                ("yes", "no"),
                description=(
                    "Did they measure catalytic ACTIVITY, as opposed to the presence of the "
                    "protein? A band on a gel, a Western blot or a fluorescence signal is not "
                    "activity: answer 'no' for those. 'yes' means an assay of what the enzyme "
                    "does -- a specific activity, a rate, a product formed in vitro."
                ),
            ),
            required=True,
        ),
        FieldSpec(
            "outcome_as_reported",
            _text(
                "What the paper says came of it, in its own words -- '3.5-fold higher DHAD "
                "specific activity', 'no detectable protein', 'active but only 12% of the "
                "cytosolic control'. Where a number is attached, it also belongs in "
                "'measurements' as its own record.",
                nullable=True,
                maximum=600,
            ),
        ),
    )


def payload_sections(vocabulary: PayloadVocabulary) -> tuple[SectionSpec, ...]:
    measurement_fields = _measurement_fields(vocabulary)
    return (
        SectionSpec(
            key="strains",
            title="Strains",
            guidance=(
                "Every strain the paper builds, uses as a parent, or uses as a control. One "
                "record per strain."
            ),
            fields=_strain_fields(),
        ),
        SectionSpec(
            key="modifications",
            title="Genetic modifications",
            guidance=(
                "One record per genetic change. A strain with four changes gives four records, "
                "not one record listing four."
            ),
            fields=_modification_fields(vocabulary),
        ),
        SectionSpec(
            key="pathway_configurations",
            title="Pathway configurations",
            guidance=(
                "How the isobutanol (or other) pathway was laid out across compartments in this "
                "build. One record per distinct configuration."
            ),
            fields=_pathway_configuration_fields(vocabulary),
        ),
        SectionSpec(
            key="measurements",
            title="Measurements",
            guidance=(
                "Every quantitative result: titers, yields, productivities, growth rates, "
                "substrate consumption. One record per number. Copy numbers exactly; never "
                "convert, average, or round."
            ),
            fields=measurement_fields,
        ),
        SectionSpec(
            key="conditions",
            title="Fermentation conditions",
            guidance=(
                "The conditions the numbers were obtained under. One record per facet, with the "
                "paper's own wording preserved."
            ),
            fields=_condition_fields(vocabulary),
        ),
        SectionSpec(
            key="bottlenecks",
            title="Bottlenecks",
            guidance=(
                "Claims that some step limits production. Only where the paper actually makes "
                "the claim or shows the data for it — an absent bottleneck is a fine answer."
            ),
            fields=_bottleneck_fields(),
        ),
        SectionSpec(
            key="co_reported_higher_alcohols",
            title="Co-reported higher alcohols",
            guidance=(
                "Ehrlich-pathway higher alcohols (isoamyl alcohol, 2-methyl-1-butanol, "
                "n-propanol, n-butanol) measured in the SAME experiment as the main product. "
                "Same fields as a measurement. These are admitted only as co-reported values "
                "(PLAN.md B.1), so a paper about one of them on its own belongs in 'measurements'."
            ),
            fields=measurement_fields,
        ),
        # Appended rather than filed next to `pathway_configurations`, where it belongs by
        # subject. Section order is the order the model is asked in, and moving an existing
        # section would reorder every future payload's keys against every stored one for no gain;
        # growth by addition keeps old and new payloads diffable.
        SectionSpec(
            key="part_expression_records",
            title="Part expression records",
            guidance=(
                "One record per part per host it was expressed in, and per compartment within "
                "that host. PLAN.md G.6: the same enzyme behaves differently in different hosts "
                "and compartments, so 'alsS in E. coli' and 'alsS in the yeast mitochondrial "
                "matrix' are two records and never one. Only parts THIS paper expressed -- an "
                "enzyme it cites someone else for is not an expression record here."
            ),
            fields=_part_expression_fields(vocabulary),
        ),
    )


#: The section keys, in payload order. Also the ``record_kind`` values a curation task carries.
RECORD_KINDS: Final[tuple[str, ...]] = (
    "strains",
    "modifications",
    "pathway_configurations",
    "measurements",
    "conditions",
    "bottlenecks",
    "co_reported_higher_alcohols",
    "part_expression_records",
)


def payload_schema(
    vocabulary: PayloadVocabulary, *, kinds: Sequence[str] | None = None
) -> JsonSchema:
    """The whole-payload JSON Schema: one array per record kind, plus the model's self-report.

    Every array is ``required``, even though any of them may be empty. An omitted key is
    ambiguous between "this paper has none" and "I did not look", and those are different answers
    to a question the atlas asks later.

    ``kinds`` narrows the schema to a subset of :data:`RECORD_KINDS`, for asking a model about one
    record kind at a time. The whole schema is ~23,300 compact characters and the largest single
    section is ~5,100, so a one-kind ask cuts the fixed per-call overhead by roughly four
    fifths -- which matters because that overhead is repeated in **every window of every paper**
    and, on a local model, is most of the context budget. Those figures were ~19,100 and ~4,200
    before ``part_expression_records`` was added: an eighth section is ~4,200 characters every
    unnarrowed call now pays on every window, which is the argument for narrowing getting stronger
    with each kind the atlas learns to ask about, not weaker.

    The ambiguity note above still holds *within* a call: the keys that are asked for stay
    required. What changes is that a narrowed call makes no claim at all about the kinds it did
    not ask about, so a caller that narrows must ask for every kind it intends to have looked at,
    or it has silently reintroduced the "I did not look" gap this docstring warns about.
    """
    sections = payload_sections(vocabulary)
    if tuple(section.key for section in sections) != RECORD_KINDS:
        raise SchemaBuildError(
            f"section keys {tuple(s.key for s in sections)} do not match RECORD_KINDS "
            f"{RECORD_KINDS}; the two must stay in step"
        )
    if kinds is not None:
        wanted = tuple(kinds)
        unknown = [k for k in wanted if k not in RECORD_KINDS]
        if unknown:
            raise SchemaBuildError(
                f"unknown record kind(s) {unknown}; known kinds are {list(RECORD_KINDS)}"
            )
        if not wanted:
            raise SchemaBuildError("kinds is empty; a payload with no sections asks nothing")
        # Kept in RECORD_KINDS order rather than the caller's, so the schema — and therefore the
        # prompt, and therefore the cache key — does not depend on argument order.
        keep = frozenset(wanted)
        sections = tuple(s for s in sections if s.key in keep)
    properties: JsonSchema = {section.key: section.array_schema() for section in sections}
    properties["self_confidence"] = {
        "type": "string",
        "enum": ["low", "medium", "high"],
        "description": (
            "How confident you are overall. Recorded as an audit trail and used for nothing: "
            "every value you extract is stored with confidence 'unverified' until a human checks "
            "it, whatever you answer here."
        ),
    }
    return {
        "type": "object",
        "required": [*(s.key for s in sections), "self_confidence"],
        "properties": properties,
        "additionalProperties": False,
    }


def section_for(vocabulary: PayloadVocabulary, key: str) -> SectionSpec:
    """The spec for one section key, or raise."""
    for section in payload_sections(vocabulary):
        if section.key == key:
            return section
    raise KeyError(f"unknown payload section {key!r}; expected one of {RECORD_KINDS}")


def record_path(kind: str, index: int) -> str:
    """``'measurements[3]'`` — the stable address of one record inside a payload.

    Stored on both the ``span`` and ``curation_task`` rows, so a curator reviewing one proposed
    value can find the quote that justified it and nothing else.
    """
    if kind not in RECORD_KINDS:
        raise KeyError(f"unknown record kind {kind!r}; expected one of {RECORD_KINDS}")
    if index < 0:
        raise ValueError(f"record index must be non-negative, got {index}")
    return f"{kind}[{index}]"


def iter_payload_records(payload: Mapping[str, Any]) -> list[tuple[str, int, JsonObject]]:
    """Flatten a payload into ``(kind, index, record)``, in ``RECORD_KINDS`` order.

    Non-list sections and non-object records are skipped rather than raising: this runs before
    the schema check in one code path (building the validator's input) and the schema check is
    what reports a malformed payload. Reporting it twice, differently, helps nobody.
    """
    flattened: list[tuple[str, int, JsonObject]] = []
    for kind in RECORD_KINDS:
        records = payload.get(kind)
        if not isinstance(records, list):
            continue
        for index, record in enumerate(records):
            if isinstance(record, dict):
                flattened.append((kind, index, record))
    return flattened


# --------------------------------------------------------------------------- typed records


def _require_str(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str):
        raise TypeError(f"{key!r} must be a string, got {value!r}")
    return value


def _optional_str(data: Mapping[str, Any], key: str) -> str | None:
    value = data.get(key)
    return value if isinstance(value, str) else None


def _require_float(data: Mapping[str, Any], key: str) -> float:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{key!r} must be a number, got {value!r}")
    return float(value)


def _optional_float(data: Mapping[str, Any], key: str) -> float | None:
    value = data.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


@dataclass(frozen=True)
class ExtractedSpan:
    """A span as the model reported it, before verification.

    Deliberately separate from :class:`fermdb.llm.validate.Span`: that one is the validator's
    input and knows how to be re-read against a source text, this one is just what arrived.
    """

    quote: str
    char_start: int
    char_end: int
    section: str | None = None

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ExtractedSpan:
        """Build from a payload record's ``span`` object."""
        start = data.get("char_start")
        end = data.get("char_end")
        if isinstance(start, bool) or not isinstance(start, int):
            raise TypeError(f"span char_start must be an integer, got {start!r}")
        if isinstance(end, bool) or not isinstance(end, int):
            raise TypeError(f"span char_end must be an integer, got {end!r}")
        return cls(
            quote=_require_str(data, "quote"),
            char_start=start,
            char_end=end,
            section=_optional_str(data, "section"),
        )


def _span_of(data: Mapping[str, Any]) -> ExtractedSpan:
    raw = data.get("span")
    if not isinstance(raw, Mapping):
        raise TypeError(f"record has no span object: {dict(data)!r}")
    return ExtractedSpan.from_mapping(raw)


@dataclass(frozen=True)
class StrainRecord:
    """One strain the paper builds, inherits or controls against."""

    name_as_reported: str
    role: str
    parent_name_as_reported: str | None
    background_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> StrainRecord:
        """Build from one validated payload record."""
        return cls(
            name_as_reported=_require_str(data, "name_as_reported"),
            role=_require_str(data, "role"),
            parent_name_as_reported=_optional_str(data, "parent_name_as_reported"),
            background_as_reported=_optional_str(data, "background_as_reported"),
            span=_span_of(data),
        )


@dataclass(frozen=True)
class ModificationRecord:
    """One genetic change. ``encoding_genome`` is not ``compartment``; see CONVENTIONS.md D1."""

    target_as_reported: str
    modification_type: str
    strain_name_as_reported: str | None
    compartment: str | None
    encoding_genome: str | None
    detail_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ModificationRecord:
        """Build from one validated payload record."""
        return cls(
            target_as_reported=_require_str(data, "target_as_reported"),
            modification_type=_require_str(data, "modification_type"),
            strain_name_as_reported=_optional_str(data, "strain_name_as_reported"),
            compartment=_optional_str(data, "compartment"),
            encoding_genome=_optional_str(data, "encoding_genome"),
            detail_as_reported=_optional_str(data, "detail_as_reported"),
            span=_span_of(data),
        )


@dataclass(frozen=True)
class PathwayConfigurationRecord:
    """How one build laid the pathway out across compartments."""

    compartment_strategy: str
    strain_name_as_reported: str | None
    enzymes_as_reported: tuple[str, ...]
    localization_as_reported: str | None
    cofactor_note_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PathwayConfigurationRecord:
        """Build from one validated payload record."""
        enzymes = data.get("enzymes_as_reported")
        return cls(
            compartment_strategy=_require_str(data, "compartment_strategy"),
            strain_name_as_reported=_optional_str(data, "strain_name_as_reported"),
            enzymes_as_reported=(
                tuple(item for item in enzymes if isinstance(item, str))
                if isinstance(enzymes, list)
                else ()
            ),
            localization_as_reported=_optional_str(data, "localization_as_reported"),
            cofactor_note_as_reported=_optional_str(data, "cofactor_note_as_reported"),
            span=_span_of(data),
        )


@dataclass(frozen=True)
class MeasurementRecord:
    """One number, with the unit it was printed in and the basis it is per.

    ``value``/``unit`` are the reported pair and are never converted here — CONVENTIONS.md,
    "Units and quantities": the declared unit is the only authority and a scale is never inferred
    from the numbers.
    """

    product_id: str
    product_as_reported: str
    quantity_kind: str
    value: float
    unit: str
    basis: str | None
    substrate: str | None
    strain_name_as_reported: str | None
    time_h: float | None
    source_locator: str
    is_digitized: bool
    #: A ceiling, not a value. A comparison treating it as a measurement overstates the strain.
    is_upper_bound: bool
    #: The assay ran and could not see it -- distinct from zero and from absent.
    is_below_lod: bool
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> MeasurementRecord:
        """Build from one validated payload record."""
        return cls(
            product_id=_require_str(data, "product_id"),
            product_as_reported=_require_str(data, "product_as_reported"),
            quantity_kind=_require_str(data, "quantity_kind"),
            value=_require_float(data, "value"),
            unit=_require_str(data, "unit"),
            basis=_optional_str(data, "basis"),
            substrate=_optional_str(data, "substrate"),
            strain_name_as_reported=_optional_str(data, "strain_name_as_reported"),
            time_h=_optional_float(data, "time_h"),
            source_locator=_require_str(data, "source_locator"),
            is_digitized=data.get("is_digitized") is True,
            is_upper_bound=data.get("is_upper_bound") is True,
            is_below_lod=data.get("is_below_lod") is True,
            span=_span_of(data),
        )


@dataclass(frozen=True)
class ConditionRecord:
    """One fermentation-condition facet, with the paper's own wording kept."""

    facet: str
    value_as_reported: str
    strain_name_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> ConditionRecord:
        """Build from one validated payload record."""
        return cls(
            facet=_require_str(data, "facet"),
            value_as_reported=_require_str(data, "value_as_reported"),
            strain_name_as_reported=_optional_str(data, "strain_name_as_reported"),
            span=_span_of(data),
        )


@dataclass(frozen=True)
class PartExpressionRecord:
    """One part, one host, one compartment, and whether it worked there.

    ``expressed_ok`` and ``activity_measured`` are separate fields and not one, for the reason
    `part_expression_record`'s own schema comment gives: *a band on a gel is not activity*. A
    single "did it work" field would let the commonest evidence in this literature — a Western
    blot showing the protein is present — stand in for the rarest and most valuable one, an assay
    showing it does anything.
    """

    part_as_reported: str
    host_as_reported: str
    compartment: str | None
    compartment_as_reported: str | None
    encoding_genome: str | None
    codon_optimized: str | None
    promoter_as_reported: str | None
    expressed_ok: str
    activity_measured: str
    outcome_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> PartExpressionRecord:
        """Build from one validated payload record."""
        return cls(
            part_as_reported=_require_str(data, "part_as_reported"),
            host_as_reported=_require_str(data, "host_as_reported"),
            compartment=_optional_str(data, "compartment"),
            compartment_as_reported=_optional_str(data, "compartment_as_reported"),
            encoding_genome=_optional_str(data, "encoding_genome"),
            # Deliberately a string and not a bool: 'yes' / 'no' / 'unknown' / absent are four
            # answers and Python's bool holds two. The promoter is what narrows it to the
            # column's 0/1/NULL, and it refuses rather than defaulting.
            codon_optimized=_optional_str(data, "codon_optimized"),
            promoter_as_reported=_optional_str(data, "promoter_as_reported"),
            expressed_ok=_require_str(data, "expressed_ok"),
            activity_measured=_require_str(data, "activity_measured"),
            outcome_as_reported=_optional_str(data, "outcome_as_reported"),
            span=_span_of(data),
        )


@dataclass(frozen=True)
class BottleneckRecord:
    """A claim that some step limits production, with who is making the claim recorded."""

    node_as_reported: str
    claim: str
    support: str
    intervention_as_reported: str | None
    span: ExtractedSpan

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> BottleneckRecord:
        """Build from one validated payload record."""
        return cls(
            node_as_reported=_require_str(data, "node_as_reported"),
            claim=_require_str(data, "claim"),
            support=_require_str(data, "support"),
            intervention_as_reported=_optional_str(data, "intervention_as_reported"),
            span=_span_of(data),
        )
