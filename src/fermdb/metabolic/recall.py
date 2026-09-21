"""The recall harness — PLAN.md phase 3's first acceptance clause.

    *"the enumerator re-discovers every published configuration (recall test against phase 1)"*

A ``pathway_configuration`` is what a paper built. A ``pathway_route`` is what
:func:`fermdb.metabolic.routes.enumerate_routes` can express. They are written in **different
vocabularies** — one in the paper's own words (``"LlAdhA RE1"``, ``"ILV genes"``, ``"2-ketoacid
decarboxylase (KDC) from Lactococcus lactis"``), the other in catalog part ids
(``adha_lactococcus``, ``kivd_lactococcus``). Deciding whether they are the same build is the
whole content of this module, and a rule that is too generous reports a recall the atlas has not
earned.

WHAT THIS TEST ACTUALLY MEASURES, which is not what its name suggests. Enumeration is the **full
cross product** of the parts catalog with the five compartment strategies. An enumerator that emits
every combination cannot fail to emit a combination it can express, so this is not a test of a
search. It is a test of **two coverage questions**:

1. does the parts catalog contain the enzymes published builds actually used?
2. does ``compartment_strategy`` contain the arrangements published builds actually used?

Every miss this harness reports is one of those two, and it names which. That makes the output a
curation worklist rather than a score, which is the more useful thing for it to be.

THE BIAS IS DELIBERATELY PESSIMISTIC. Where the record is ambiguous the harness reports a miss or
refuses to judge, never a match. A recall figure that is too high is the failure mode that matters:
it would license the claim "the atlas re-discovers the literature" on evidence that does not
support it. A figure that is too low costs a curator an afternoon.

THREE NUMBERS, NEVER ONE. ``recall`` is over the configurations that *can* be judged;
``coverage`` says what fraction that was, so nothing hides in the not-evaluable bucket; and
``partial`` says what recall would be if a configuration naming three of five enzymes counted.
Reporting only the first would be the same inflation by a different route.

THREE KINDS OF MATCH, COUNTED APART. A role resolves in one of three ways, and they are not the
same identification:

* by an **exact gene symbol** — token equality against ``part.genes`` plus :data:`ENZYME_ALIASES`;
* by a **gene symbol narrowed with a variant designation** — ``ilvC6E6``, ``ilvC P2D1-A1`` — under
  the owner's second ruling of 2026-09-22, and then only where exactly one catalog part carries
  that symbol *and* that designation;
* by a **role name qualified with a source organism** — "2-ketoacid decarboxylase (KDC) from
  Lactococcus lactis" — under the owner's first ruling of 2026-09-22, and then only where the
  catalog holds exactly one part for that ``(step_role, source_organism)`` pair.

The three are never allowed to disappear into one total: every verdict names the roles it resolved
each way and :class:`RecallReport` counts them apart, so a reader of a recall figure can see how
much of it rests on which. The two rulings have **the same shape — a qualified name identifies, a
bare one does not**. A bare role name with no organism stays refused because it is a wildcard, and
a wildcard returns 100% on a record that said nothing. A bare ``ilvC`` with no variant stays
ambiguous and is never narrowed, because four KARI parts carry that symbol and differ by exactly
the NADPH/NADH question the programme turns on: picking one would be picking a cofactor.

The rule itself is :data:`MATCHING_RULE` — a list of clauses, in the order they are applied,
printed by ``fermdb atlas recall --rule``. It is data rather than prose in a docstring so that
:func:`classify` cannot drift from it: every outcome reason this module produces names the clause
that produced it, and ``tests/test_recall.py`` asserts the two sets agree.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from .curated import Part
from .routes import STEP_ORDER, STRATEGY_PLANS, Route

__all__ = [
    "BY_GENE_SYMBOL",
    "BY_SOURCE_ORGANISM",
    "BY_VARIANT_DESIGNATION",
    "ENZYME_ALIASES",
    "MATCHING_RULE",
    "AmbiguousSource",
    "AmbiguousVariant",
    "Configuration",
    "ConfigurationVerdict",
    "RecallReport",
    "RoleResolution",
    "RuleClause",
    "classify",
    "designation_index",
    "describe_report",
    "enzyme_entries",
    "gene_index",
    "load_configurations",
    "recall_report",
    "reported_designations",
    "resolve_roles",
    "source_organism_of",
]


# --------------------------------------------------------------------------------- the rule


@dataclass(frozen=True)
class RuleClause:
    """One clause of the matching rule, with the reason string it emits."""

    name: str
    #: 'matched' | 'missed' | 'not_evaluable' — what a configuration falling to this clause is.
    outcome: str
    text: str


#: THE MATCHING RULE, in the order the clauses are applied. First applicable clause wins.
#:
#: This is the deliverable the acceptance criterion turns on, so it is written here in full rather
#: than being implied by :func:`classify`. Each clause says what it checks and why it is drawn
#: where it is drawn; the ones that concede something say what they concede.
MATCHING_RULE: Final[tuple[RuleClause, ...]] = (
    RuleClause(
        "strategy_not_enumerable",
        "not_evaluable",
        "The configuration's compartment_strategy_id is not one of the five strategies the "
        "enumerator plans for (or is NULL). There is no route to compare it against, and calling "
        "that a miss would blame the enumerator for a build it was never asked to express. "
        "Extraction really does produce 'unknown' and 'NA' here, so this bucket will not be empty.",
    ),
    RuleClause(
        "host_not_recorded",
        "not_evaluable",
        "host_strain_id is NULL. A configuration's host is what makes it comparable to another "
        "one (promote.py refuses to guess it), so a configuration without one cannot be placed "
        "inside or outside the enumerator's scope.",
    ),
    RuleClause(
        "host_outside_enumeration",
        "not_evaluable",
        "The host strain's organism is not the selected chassis's organism. enumerate_routes has "
        "NO host axis at all — G.7's product says 'x host' and the implementation does not vary "
        "one — so every enumerated route is implicitly a yeast route: matrix and peroxisomal "
        "compartments, and a strategy E that means mtDNA. Counting an E. coli build as "
        "re-discovered by a yeast enumeration would be a false recall of the plainest kind. "
        "CONCEDES: this also means the atlas cannot yet claim recall over 'any host', which is "
        "what phase 1 curates. See docs/drafts/phase3/ACCEPTANCE.md, decision D2.",
    ),
    RuleClause(
        "no_enzyme_set_recorded",
        "not_evaluable",
        "The description carries no 'enzymes as reported:' segment — the shape "
        "curate/promote.py writes — so no enzyme set was recorded. The harness reads ONLY that "
        "segment and never the 'localization as reported:' prose beside it, because that prose "
        "names genes the build removed ('circumventing Bat1p and Bat2p') and genes that are "
        "targeting tags ('Cox4'). Harvesting names out of it would attribute enzymes to builds "
        "that did not use them, which is exactly the too-loose rule this module exists to avoid.",
    ),
    RuleClause(
        "matched",
        "matched",
        "All five step roles resolved to at least one catalog part, and some enumerated route of "
        "the same strategy uses, at every role, one of that role's resolved parts. A role resolves "
        "in one of THREE ways, and they are not the same identification: (a) by EXACT gene-symbol "
        "token equality (case-folded) against part.genes, plus the curated ENZYME_ALIASES table — "
        "never substring, never fuzzy; or (b) by a gene symbol NARROWED WITH A VARIANT DESIGNATION "
        "('ilvC6E6', 'ilvC P2D1-A1'), under the owner's second ruling of 2026-09-22, and only "
        "where exactly one part carries that symbol AND that designation — see "
        "variant_designation_ambiguous for the safeguard and for why a BARE ilvC is still not "
        "narrowed; or (c) by a role name QUALIFIED WITH A SOURCE ORGANISM ('2-ketoacid "
        "decarboxylase (KDC) from Lactococcus lactis'), under the owner's first ruling of the same "
        "day, and only where the catalog holds exactly one part for that (step_role, "
        "source_organism) pair — see source_organism_ambiguous for that safeguard and for why a "
        "role name WITHOUT an organism is still refused. The two rulings have the same shape: A "
        "QUALIFIED NAME IDENTIFIES, A BARE ONE DOES NOT. Every verdict says which kinds it used, "
        "and the report counts all three separately, so a reader of a recall figure can see how "
        "much of it rests on which rather than having to assume. A role that still resolved to "
        "more than one part is reported as ambiguous beside the match, because a bare ilvC is "
        "carried by four KARI parts that differ by exactly the NADPH/NADH question the atlas is "
        "for.",
    ),
    RuleClause(
        "catalog_gap",
        "missed",
        "A role is unfilled AND the configuration names at least one enzyme entry the catalog "
        "does not recognise. This is a genuine miss: the build used an enzyme no part carries, so "
        "no enumerated route can be that build. The unrecognised entries are printed verbatim "
        "beside the verdict, so a reader can see at once whether the gap is real (ADH7, yqhD — "
        "curate a part) or an artifact of vague prose. CONCEDES: an unrecognised entry that is "
        "only a variant spelling of an already-filled role (ILV6V90D/L91F) is counted here too, "
        "which makes the figure pessimistic rather than generous. That is the intended direction.",
    ),
    RuleClause(
        "source_organism_ambiguous",
        "not_evaluable",
        "A role is unfilled because the record identified its enzyme as 'ROLE from ORGANISM' and "
        "the catalog holds MORE THAN ONE part for that (step_role, source_organism) pair. The "
        "owner ruled on 2026-09-22 that a role name qualified by a source organism IS a real "
        "identification and not a wildcard — '2-ketoacid decarboxylase (KDC) from Lactococcus "
        "lactis' names a protein by where it was cloned from, the way a paper's Methods does — "
        "but only for as long as the catalog can name exactly one part for it. Where two or more "
        "can, the harness REFUSES and names them rather than picking: choosing between two "
        "Lactococcus KDCs is a curation claim about which enzyme the paper used, and making it "
        "silently inside a matcher would put the claim in the one place nobody would look for it. "
        "THE REFUSAL IS A PROPERTY OF TODAY'S CATALOG, NOT OF THE RECORD. Uniqueness is recomputed "
        "on every run, so curating a second Lactococcus KDC tomorrow turns today's resolved "
        "matches into this clause by itself — a stale resolution cannot outlive the fact that made "
        "it safe. WHY A BARE ROLE NAME IS STILL REFUSED, which this clause does not erode: 'KDC' "
        "alone says which STEP ran, never which protein; it carries no organism, so there is "
        "nothing for uniqueness to bite on and it would resolve to every KDC part in the catalog. "
        "That is a wildcard, and it would let a configuration naming nothing match every route of "
        "its strategy and report 100% recall on an empty record. The organism is exactly what "
        "turns the phrase into an identification; without one the clause below applies. An "
        "organism that parses but matches NO part of that role is also refused, and falls through "
        "below rather than being guessed at.",
    ),
    RuleClause(
        "variant_designation_ambiguous",
        "not_evaluable",
        "A role is unfilled because the record named a gene symbol PLUS a variant designation "
        "('ilvC6E6', 'ilvC P2D1-A1') and MORE THAN ONE catalog part carries that symbol and that "
        "designation. The owner ruled on 2026-09-22 that a variant designation IS the "
        "identification — 6E6 and P2D1-A1 are what the papers use, and ilvC6E6 names a specific "
        "engineered protein the way ilvC does not — but, exactly as for a source organism, only "
        "for as long as the catalog can name one part for it. Where two or more can, the harness "
        "REFUSES and names them rather than picking. This is the SAME SHAPE as the role+organism "
        "ruling: a qualified name identifies, a bare one does not, and uniqueness is the price of "
        "both. Uniqueness is recomputed on every run from the parts passed in, so curating a "
        "second ilvC 6E6 tomorrow turns today's resolved match into this clause by itself. WHY "
        "THE REFUSAL IS HARSHER THAN A BARE ilvC, which looks backwards until you read what the "
        "record claimed: a bare ilvC claims nothing about the cofactor, so reporting it as "
        "'matched, ambiguous at KARI' concedes exactly what the record conceded. A record that "
        "wrote 6E6 DID name the cofactor, and falling back to an ambiguous match would average "
        "over the one property it was naming — NADPH against NADH, which is the distinction this "
        "whole programme turns on. WHY A BARE ilvC IS STILL NOT NARROWED, which this clause does "
        "not erode: four KARI parts carry ilvC (ilvc_ecoli, ilvc_nadh_variant, ilvc6e6_ecoli, "
        "ilvc_p2d1a1_ecoli) and they differ by the NADPH/NADH question and almost nothing else, "
        "so the symbol alone identifies nothing and resolving it would SILENTLY PICK A COFACTOR — "
        "the one property the atlas exists to reason about. It stays ambiguous, reported and "
        "never narrowed. A designation the parser cannot confidently read, and a designation that "
        "matches NO part, both leave the role ambiguous rather than guessing.",
    ),
    RuleClause(
        "under_specified",
        "not_evaluable",
        "A role is unfilled and every enzyme entry was recognised — the record simply does not "
        "say which enzyme ran that step, often naming only the role ('KDC', 'ADH') or the gene "
        "family ('ILV genes', 'the Ehrlich pathway'; see _ROLE_SYNONYMS). "
        "A role name is NOT an enzyme identification and is never treated as a wildcard: allowing "
        "it would let a configuration naming nothing match all 120 routes of its strategy and "
        "return 100% recall on an empty record. The one qualification a role name can carry that "
        "makes it an identification is a SOURCE ORGANISM, and it must still resolve uniquely — "
        "see source_organism_ambiguous. Counted in `partial` instead, and never in `recall`.",
    ),
)

_CLAUSE_BY_NAME: Final[Mapping[str, RuleClause]] = {c.name: c for c in MATCHING_RULE}


#: Reported spellings that are the same gene as a catalog part's symbol, each with its reason.
#:
#: This is curation, deliberately small, deliberately explicit, and deliberately NOT a rule. A
#: generic "strip a two-letter genus prefix" rule is a substring match wearing a hat: it would
#: silently turn any token ending in a gene symbol into a match, and the first false positive
#: would be invisible. A table of named exceptions fails loudly instead — an unknown spelling
#: stays unrecognised and shows up in the report, where a curator can see it and decide.
#:
#: A curator adding a row here is making a claim ("the paper's X is the catalog's gene Y") and
#: should leave the reason, as these do.
ENZYME_ALIASES: Final[Mapping[str, str]] = {
    # 'Ll' is the Lactococcus lactis genus prefix papers put in front of the gene symbol; the
    # proposals in this atlas carry both "LlAdhA RE1" and plain "LlAdhA".
    "lladha": "adhA",
    "llkivd": "kivD",
    # Named engineered KARI variants, written with the designation GLUED to the symbol. They
    # alias to the GENE symbol and never to a part id — an alias that named a part would be the
    # cofactor claim made in a lookup table. What the alias buys, since the owner's second ruling
    # of 2026-09-22, is that the glue can be split on a boundary a CURATOR asserted: the target
    # symbol is a prefix of the key, so the remainder is the designation and
    # `variant_designation_ambiguous` decides whether it identifies a part. `ilvcp2d1` still
    # narrows nothing — no part carries the designation `P2D1` — and stays ambiguous, which is the
    # conservative half working.
    "ilvc6e6": "ilvC",
    "ilvcp2d1": "ilvC",
    "ilvcp2d1a1": "ilvC",
    # The valine-insensitive ILV6, as two point mutations written onto the symbol.
    "ilv6v90d": "ILV6",
    "ilv6v90dl91f": "ILV6",
}

#: Tokens inside an enzyme entry, as words. '(P2D1-A1)' splits, so 'Ec_ilvC(P2D1-A1)' yields
#: 'Ec', 'ilvC', 'P2D1', 'A1' and the gene symbol is reachable without any substring test.
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*")

#: The exact prefix `curate/promote.py::_configuration_description` writes.
_ENZYME_PREFIX: Final[str] = "enzymes as reported:"
_LOCALIZATION_PREFIX: Final[str] = "localization as reported:"

#: Step-role names, case-folded. A token equal to one of these names the STEP, not the enzyme.
_ROLE_TOKENS: Final[frozenset[str]] = frozenset(role.casefold() for role in STEP_ORDER)

#: Case-folded role token -> the STEP_ORDER spelling, so a parsed role keeps the canonical name.
_ROLE_BY_TOKEN: Final[Mapping[str, str]] = {role.casefold(): role for role in STEP_ORDER}

#: How a role was resolved. Reported, never averaged: the two are different strengths of evidence
#: and a figure that pooled them would hide exactly what the owner's 2026-09-22 ruling exposed.
BY_GENE_SYMBOL: Final[str] = "gene_symbol"
BY_SOURCE_ORGANISM: Final[str] = "source_organism"
BY_VARIANT_DESIGNATION: Final[str] = "variant_designation"

#: Tokens that name a GROUP of steps rather than an enzyme. The same category as a bare role
#: name: the paper said which steps, not which proteins.
#:
#: "the ILV genes" appears verbatim in this atlas's own extractions, used exactly the way "KDC"
#: and "ADH" are used, and without it a configuration saying "ARO10, LlAdhA RE1, ILV genes" is
#: reported as a CATALOG GAP -- as though the atlas were missing a part called "ILV genes" --
#: when what is missing is the paper naming its upstream enzymes. Both verdicts are not-a-match;
#: the distinction matters because one of them is a curation worklist item and the other is not,
#: and the whole value of the miss list is that every entry on it is actionable.
#:
#: A NAMED TABLE, NOT A PREFIX RULE. 'ILV2' must resolve to a part; only the bare family name is
#: vague. A rule that treated any token starting 'ilv' as a family name would swallow the parts.
_ROLE_SYNONYMS: Final[Mapping[str, tuple[str, ...]]] = {
    # The yeast gene family for the three upstream steps, named as a block.
    "ilv": ("AHAS", "KARI", "DHAD"),
    # The Ehrlich pathway is the decarboxylation and the reduction, named as a block.
    "ehrlich": ("KDC", "ADH"),
}


# ------------------------------------------------------------------- 'ROLE from ORGANISM'
#
# The owner's 2026-09-22 ruling: a role name qualified by a source organism is a real enzyme
# identification, resolvable against `part.source_organism`, but ONLY where the catalog holds
# exactly one part for that (step_role, source_organism) pair. Everything below is deliberately
# narrow. A parse this code is not sure of returns None and the entry falls through to the
# existing `role_named_only` / `under_specified` path, because a wrong organism is a wrong enzyme
# and a wrong enzyme is a false recall — the one outcome this module exists to prevent.

#: The connective that introduces a source organism. The LAST one in the entry wins, so
#: '... (KDC) from Lactococcus lactis' is read from the right.
_FROM = re.compile(r"\bfrom\b", re.IGNORECASE)

#: A word of an organism phrase. Keeps the trailing '.' of an abbreviated genus ('L.') and the
#: hyphen of a strain ('K-12'); the species epithet is checked for being alphabetic separately.
_ORGANISM_WORD = re.compile(r"[A-Za-z][A-Za-z0-9\-]*\.?")


def _binomial(text: str) -> tuple[str, str] | None:
    """``(genus-or-initial, species)``, case-folded, or None when the text is not a binomial.

    Accepts the three shapes the literature actually writes: ``Lactococcus lactis``, the
    abbreviated ``L. lactis``, and either of those with a strain or subspecies suffix
    (``Lactococcus lactis subsp. lactis IFPL730``, ``Escherichia coli K-12``) — the suffix is
    ignored, because a strain is not a different source organism for the purpose of asking which
    catalog part an author meant.

    Everything past the first two words is discarded rather than interpreted, and a phrase with
    fewer than two words, a non-alphabetic genus or species, or a species of fewer than three
    letters is NOT a binomial. That last guard is what stops 'from the KDC step' and similar prose
    from being read as an organism.
    """
    words = _ORGANISM_WORD.findall(text)
    if len(words) < 2:
        return None
    genus, species = words[0].rstrip("."), words[1].rstrip(".")
    if not genus.isalpha() or not species.isalpha() or len(species) < 3:
        return None
    return genus.casefold(), species.casefold()


def _organisms_agree(reported: tuple[str, str], catalog: tuple[str, str]) -> bool:
    """Do a reported binomial and a catalog one name the same organism?

    The species epithet must be equal outright. The genus is compared in full unless one side is a
    single-letter abbreviation, in which case only the initial can be compared — which is
    genuinely weaker ('L. lactis' is also *Leuconostoc lactis*). That weakness is not patched over
    here: it is left to the uniqueness requirement, which counts the matching PARTS, so an
    abbreviation spanning two catalog genera produces two candidates and is refused as ambiguous.
    """
    if reported[1] != catalog[1]:
        return False
    reported_genus, catalog_genus = reported[0], catalog[0]
    if len(reported_genus) == 1 or len(catalog_genus) == 1:
        return reported_genus[0] == catalog_genus[0]
    return reported_genus == catalog_genus


def source_organism_of(entry: str) -> str | None:
    """The organism phrase an entry names after 'from', or None when it does not name one.

    Returns the phrase verbatim (so a verdict can quote what it read) and only when that phrase
    parses as a binomial. ``'ADH7'`` -> None; ``'KDC'`` -> None; ``'a KDC from L. lactis'`` ->
    ``'L. lactis'``.
    """
    connectives = list(_FROM.finditer(entry))
    if not connectives:
        return None
    phrase = entry[connectives[-1].end() :].strip(" \t,;:()")
    return phrase if _binomial(phrase) is not None else None


def _sole_step_role(tokens: Sequence[str]) -> str | None:
    """The ONE step role an entry names, or None when it names none, several, or a family block.

    Several, or a block, is refused rather than resolved role by role. 'ILV genes from
    Saccharomyces cerevisiae' names three steps at once and the record still has not said which
    protein ran any of them; resolving all three from the organism would be the wildcard wearing a
    binomial, which is the thing the ruling was careful not to authorise.
    """
    if any(token in _ROLE_SYNONYMS for token in tokens):
        return None
    roles = {_ROLE_BY_TOKEN[token] for token in tokens if token in _ROLE_BY_TOKEN}
    return roles.pop() if len(roles) == 1 else None


# ------------------------------------------------------- 'GENE SYMBOL + VARIANT DESIGNATION'
#
# The owner's second 2026-09-22 ruling, deliberately the same shape as the first: a variant
# designation attached to a gene symbol IS the identification — `6E6` and `P2D1-A1` are what the
# papers use — and it resolves only where exactly one catalog part carries that symbol and that
# designation. A BARE `ilvC` is not narrowed and never will be here.
#
# This is the one place in the module where a token is split rather than compared whole, which is
# the "substring match wearing a hat" the rest of the file refuses. Four things keep it honest:
#
# 1. NARROWING ONLY. A designation can only remove candidates from a role a GENE SYMBOL already
#    filled. It can never fill an empty role, never reach a part the symbol did not reach, and
#    never turn an unrecognised entry into a recognised one. So the worst a misread designation
#    can do is refuse a match that would otherwise have been reported ambiguous — a move in the
#    pessimistic direction, which is the direction this module is allowed to be wrong in.
# 2. THE SPLIT POINT IS CURATED, NOT GUESSED. A glued token (`ilvC6E6`) is split only where it is
#    an ENZYME_ALIASES key whose target symbol is a prefix of it — i.e. where a curator has
#    already written down that this spelling is that gene. An unknown glued spelling stays
#    unrecognised, exactly as before.
# 3. THE CATALOG SIDE IS DECLARED. A part carries a designation only if it declares `variant_of`,
#    which is the catalog saying "this is a variant of that"; the designation is then read from
#    the part id. A variant part whose id does not spell its designation carries none and cannot
#    be reached by this clause — refused, not guessed.
# 4. SHAPE. A designation must mix letters and digits. That is what `6E6`, `P2D1A1` and `V90D`
#    look like and what `nadh`, `native`, `ecoli` and `variant` do not, so the descriptive words
#    in part ids are not mistaken for designations. A token that is itself a catalog gene symbol
#    is never a designation.

#: The longest thing we will read as a designation. `P2D1A1` is 6; the bound is here so a run of
#: tokens cannot be concatenated into something no paper wrote.
_DESIGNATION_MAX: Final[int] = 16

_HAS_DIGIT = re.compile(r"[0-9]")
_HAS_LETTER = re.compile(r"[A-Za-z]")

#: Tokens for the designation scan. Unlike :data:`_TOKEN` these may BEGIN with a digit, because
#: papers write `ilvC 6E6` and `6E6` is the whole of the designation. `_TOKEN` keeps its
#: letter-first shape, because it feeds gene-symbol lookup and no gene symbol starts with a digit.
#:
#: Scanning with it IS the normalisation: separators fall between the runs and the runs are
#: case-folded and concatenated, so `P2D1-A1`, `P2D1A1` and `p2d1 a1` all reach the one key
#: `p2d1a1`. The difference between those spellings is typography, not identity.
_ALNUM_RUN = re.compile(r"[A-Za-z0-9]+")


def _is_designation(key: str, known_genes: Collection[str]) -> bool:
    """Is this normalised token something we can confidently read as a variant designation?

    Conservative on purpose: a token that fails here leaves the match AMBIGUOUS rather than being
    guessed at. It must mix letters and digits — which `6E6`, `P2D1A1` and `V90D` do and `nadh`,
    `native`, `ecoli` and `variant` do not — and it must not itself be a gene symbol the catalog
    carries, or `ilv2_ilv6_native` would read its second gene as a designation of its first.
    """
    if not 2 <= len(key) <= _DESIGNATION_MAX or key in known_genes:
        return False
    return bool(_HAS_DIGIT.search(key)) and bool(_HAS_LETTER.search(key))


def _designations_of(part: Part, known_genes: Collection[str]) -> frozenset[str]:
    """The variant designation(s) a catalog part carries, read from its id.

    ONLY for a part that declares ``variant_of``. That field is the catalog asserting that this
    part is a variant of another one — which is exactly what D3 said a curator would have to add
    before the harness could key on anything — and without it no designation is read at all, so
    no ordinary part can acquire one by an accident of naming.

    The id is read segment by segment: a segment that begins with one of the part's own gene
    symbols yields either its own remainder (``ilvc6e6`` -> ``6e6``) or, when the segment IS the
    symbol, the next segment (``ilvc_p2d1a1_ecoli`` -> ``p2d1a1``). Either way the candidate must
    pass :func:`_is_designation`, which is why ``ilvc_nadh_variant`` carries none: ``nadh`` is a
    word about the cofactor, not a designation a paper would cite.
    """
    if part.variant_of is None:
        return frozenset()
    segments = [segment for segment in part.id.casefold().split("_") if segment]
    genes = sorted({gene.casefold() for gene in part.genes}, key=len, reverse=True)
    found: set[str] = set()
    for index, segment in enumerate(segments):
        for gene in genes:
            if not segment.startswith(gene):
                continue
            remainder = segment[len(gene) :]
            candidate = remainder if remainder else (segments + [""])[index + 1]
            if _is_designation(candidate, known_genes):
                found.add(candidate)
            break
    return frozenset(found)


def designation_index(parts: Sequence[Part]) -> dict[str, frozenset[str]]:
    """``part id -> the variant designation keys it carries``, over the whole catalog.

    Recomputed from the parts passed in, never cached, for the same reason the organism clause's
    uniqueness is: it is a fact about the catalog as it is now, and a resolution that outlived the
    fact that made it safe is the failure mode both rulings were careful to avoid.
    """
    known = set(gene_index(parts))
    return {part.id: _designations_of(part, known) for part in parts}


def reported_designations(entry: str, known_genes: Collection[str]) -> dict[str, str]:
    """``designation key -> the text the entry wrote it as``, for one enzyme entry.

    Two shapes, and no third:

    * **detached** — ``'ilvC 6E6'``, ``'ilvC-6E6'``, ``'IlvC^6E6'``, ``'Ec_ilvC(P2D1-A1)'``. The
      designation is the run of tokens IMMEDIATELY FOLLOWING a token that resolved to a gene
      symbol. A run is offered whole and prefix by prefix, so ``P2D1`` then ``A1`` yields both
      ``p2d1`` and ``p2d1a1`` and the catalog decides which it knows;
    * **glued** — ``'ilvC6E6'``. Split only at a boundary :data:`ENZYME_ALIASES` already asserts:
      the key's target gene symbol must be a case-folded prefix of the key. An unknown glued
      spelling is not split, is not recognised, and is reported as it always was.

    Adjacency is required in both shapes. A designation floating elsewhere in the entry is not
    read, because "a token that looks like a designation somewhere in this text" is the loose rule
    this module exists to avoid.
    """
    matches = list(_ALNUM_RUN.finditer(entry))
    tokens = [m.group(0) for m in matches]
    keys = [token.casefold() for token in tokens]
    found: dict[str, str] = {}

    for index, key in enumerate(keys):
        gene = ENZYME_ALIASES.get(key, key).casefold()
        if gene not in known_genes:
            continue
        if key != gene and key.startswith(gene):
            # Glued, on a boundary a curator wrote down.
            remainder = key[len(gene) :]
            if _is_designation(remainder, known_genes):
                found.setdefault(remainder, tokens[index][len(gene) :])
        run = ""
        for following in range(index + 1, len(keys)):
            candidate = keys[following]
            if candidate in known_genes or candidate in ENZYME_ALIASES:
                break
            if not _is_designation(candidate, known_genes):
                break
            run += candidate
            if len(run) > _DESIGNATION_MAX:
                break
            found.setdefault(run, entry[matches[index + 1].start() : matches[following].end()])
    return found


# ------------------------------------------------------------------------------- the records


@dataclass(frozen=True)
class Configuration:
    """One ``pathway_configuration`` row, plus the organism its host strain belongs to."""

    id: str
    name: str
    compartment_strategy_id: str | None
    host_strain_id: str | None
    host_organism_id: str | None
    host_organism_name: str | None
    description: str


def load_configurations(conn: sqlite3.Connection) -> tuple[Configuration, ...]:
    """Every published configuration, with its host's organism resolved.

    LEFT JOINs throughout: a configuration with no host, or a host strain whose organism row is
    absent, is a record this harness must be able to report on rather than one it may drop.
    """
    rows = conn.execute(
        "SELECT c.id, c.name, c.compartment_strategy_id, c.host_strain_id, "
        "       s.organism_id AS host_organism_id, o.name AS host_organism_name, "
        "       COALESCE(c.description, '') AS description "
        "FROM pathway_configuration c "
        "LEFT JOIN strain s ON s.id = c.host_strain_id "
        "LEFT JOIN organism o ON o.id = s.organism_id "
        "ORDER BY c.id"
    ).fetchall()
    return tuple(
        Configuration(
            id=str(row["id"]),
            name=str(row["name"]),
            compartment_strategy_id=row["compartment_strategy_id"],
            host_strain_id=row["host_strain_id"],
            host_organism_id=row["host_organism_id"],
            host_organism_name=row["host_organism_name"],
            description=str(row["description"]),
        )
        for row in rows
    )


# -------------------------------------------------------------------------------- resolution


def enzyme_entries(description: str) -> tuple[str, ...]:
    """The enzyme set as the paper named it, taken ONLY from the 'enzymes as reported:' segment.

    Returns ``()`` when the segment is absent, which is a different state from an empty enzyme
    list and is classified separately (``no_enzyme_set_recorded``).

    The segment ends at '; localization as reported:' because that is how
    ``_configuration_description`` joins them; everything after it is prose about where the
    enzymes went, and is never read for enzyme names. See the rule clause for why.
    """
    lowered = description.casefold()
    start = lowered.find(_ENZYME_PREFIX)
    if start < 0:
        return ()
    segment = description[start + len(_ENZYME_PREFIX) :]
    end = segment.casefold().find(_LOCALIZATION_PREFIX)
    if end >= 0:
        # Drop the '; ' the joiner put in front of the next section.
        segment = segment[:end].rstrip().rstrip(";")
    return tuple(entry.strip() for entry in segment.split(",") if entry.strip())


def gene_index(parts: Sequence[Part]) -> dict[str, tuple[str, ...]]:
    """Case-folded gene symbol -> the part ids carrying it, over the WHOLE catalog.

    The whole catalog, including ``cofactor_cycle`` parts (POS5, ADH3), because this index answers
    "does the atlas know this gene at all" — which is what decides whether an unfilled role is a
    catalog gap or vague prose. Role resolution uses the same index but filters to the five step
    roles afterwards, in :func:`resolve_roles`.
    """
    index: dict[str, list[str]] = {}
    for part in parts:
        for gene in part.genes:
            index.setdefault(gene.casefold(), []).append(part.id)
    return {gene: tuple(sorted(ids)) for gene, ids in index.items()}


@dataclass(frozen=True)
class RoleResolution:
    """What the configuration said about one step role."""

    role: str
    #: Part ids this role could be. Empty means the record did not identify the enzyme.
    part_ids: tuple[str, ...]
    #: The entries that produced them, verbatim, so a verdict can be audited without re-running.
    from_entries: tuple[str, ...]
    #: How the record identified this enzyme: :data:`BY_GENE_SYMBOL`, :data:`BY_SOURCE_ORGANISM`,
    #: or both when two entries agreed by different routes. Never collapsed to a boolean — a
    #: reader of a recall figure is entitled to know which kind of identification it rests on.
    resolved_by: tuple[str, ...] = ()

    @property
    def filled(self) -> bool:
        return bool(self.part_ids)

    @property
    def ambiguous(self) -> bool:
        return len(self.part_ids) > 1


@dataclass(frozen=True)
class AmbiguousSource:
    """A 'ROLE from ORGANISM' phrase the catalog cannot narrow to one part.

    A refusal, not a pick.
    """

    role: str
    #: The enzyme entry verbatim, so the refusal quotes the record rather than paraphrasing it.
    entry: str
    #: The organism phrase as the record wrote it.
    organism: str
    #: The parts that share this (step_role, source_organism) pair — all of them, named.
    part_ids: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.entry!r} identifies {self.role} only as {self.organism!r}, and the catalog "
            f"holds {len(self.part_ids)} parts for that (step_role, source_organism) pair "
            f"({', '.join(self.part_ids)}) — picking one would be a curation claim"
        )


@dataclass(frozen=True)
class AmbiguousVariant:
    """A 'GENE + DESIGNATION' the catalog cannot narrow to one part.

    A refusal, not a pick — and, unlike a bare symbol's ambiguity, not a match either. The record
    named the variant, which is to say it named the cofactor; averaging over it would discard the
    one property the designation was carrying.
    """

    role: str
    #: The enzyme entry verbatim, so the refusal quotes the record rather than paraphrasing it.
    entry: str
    #: The designation as the record wrote it ('6E6', 'P2D1-A1').
    designation: str
    #: The parts carrying that symbol AND that designation — all of them, named.
    part_ids: tuple[str, ...]

    def describe(self) -> str:
        return (
            f"{self.entry!r} identifies {self.role} by the variant designation "
            f"{self.designation!r}, and {len(self.part_ids)} catalog parts carry that symbol and "
            f"that designation ({', '.join(self.part_ids)}) — picking one would be picking a "
            f"cofactor"
        )


@dataclass(frozen=True)
class Resolution:
    """The configuration's enzyme set, mapped onto the enumerator's coordinates."""

    roles: tuple[RoleResolution, ...]
    #: Entries naming a step role but no enzyme ('KDC', 'ILV genes'). A curation limit.
    role_named_only: tuple[str, ...]
    #: Entries the catalog does not recognise at all. A catalog gap, or prose.
    unrecognised: tuple[str, ...]
    #: Entries naming a role AND an organism that the catalog cannot narrow to one part.
    ambiguous_sources: tuple[AmbiguousSource, ...] = ()
    #: Entries naming a gene AND a variant designation that the catalog cannot narrow to one part.
    ambiguous_variants: tuple[AmbiguousVariant, ...] = ()

    @property
    def unfilled_roles(self) -> tuple[str, ...]:
        return tuple(r.role for r in self.roles if not r.filled)

    @property
    def ambiguous_roles(self) -> tuple[str, ...]:
        return tuple(r.role for r in self.roles if r.ambiguous)

    @property
    def organism_resolved_roles(self) -> tuple[str, ...]:
        """Roles whose enzyme was identified by role-plus-organism rather than by a gene symbol."""
        return tuple(r.role for r in self.roles if BY_SOURCE_ORGANISM in r.resolved_by)

    @property
    def variant_resolved_roles(self) -> tuple[str, ...]:
        """Roles whose part was pinned by a variant designation narrowing a shared gene symbol."""
        return tuple(r.role for r in self.roles if BY_VARIANT_DESIGNATION in r.resolved_by)


def resolve_roles(entries: Sequence[str], parts: Sequence[Part]) -> Resolution:
    """Map the paper's enzyme names onto step roles and part ids.

    EXACT token equality, case-folded, against ``part.genes`` and :data:`ENZYME_ALIASES`. Never a
    substring test: 'ADH7' must not resolve to ADH1 because one contains 'ADH', and 'LlAdhA' is
    an alias precisely so that the general case stays strict.

    A role a gene symbol filled with MORE THAN ONE part is then NARROWED, where the same entry
    carries a variant designation ('ilvC6E6', 'ilvC P2D1-A1') that exactly one of those parts
    carries — the owner's second 2026-09-22 ruling, flagged :data:`BY_VARIANT_DESIGNATION`. Two or
    more parts carrying the designation is a refusal recorded in ``ambiguous_variants``, and the
    role is left UNFILLED rather than falling back to the ambiguous symbol. A bare symbol, or a
    designation no part carries, narrows nothing and stays ambiguous.

    An entry no gene symbol recognises gets a SECOND chance, added under the owner's 2026-09-22
    ruling: if it names exactly one step role and one source organism ('... (KDC) from Lactococcus
    lactis'), and the catalog holds exactly one part for that pair, the role resolves and is
    flagged :data:`BY_SOURCE_ORGANISM`. Two or more parts for the pair is a refusal recorded in
    ``ambiguous_sources``, never a pick. Uniqueness is recomputed here on every call, from the
    ``parts`` passed in, so it tracks the catalog rather than a snapshot of it.
    """
    by_gene = gene_index(parts)
    role_of = {part.id: part.step_role for part in parts}
    designations = designation_index(parts)

    found: dict[str, set[str]] = {role: set() for role in STEP_ORDER}
    entries_for: dict[str, set[str]] = {role: set() for role in STEP_ORDER}
    resolved_by: dict[str, set[str]] = {role: set() for role in STEP_ORDER}
    role_named_only: list[str] = []
    unrecognised: list[str] = []
    ambiguous_sources: list[AmbiguousSource] = []
    ambiguous_variants: list[AmbiguousVariant] = []

    for entry in entries:
        tokens = [token.casefold() for token in _TOKEN.findall(entry)]
        recognised = False
        names_a_role = any(token in _ROLE_TOKENS or token in _ROLE_SYNONYMS for token in tokens)
        # Collected per ENTRY, not per configuration: a designation may only narrow the role the
        # same entry filled. A '6E6' in one entry has nothing to say about another entry's gene.
        by_symbol: dict[str, set[str]] = {}
        for token in tokens:
            gene = ENZYME_ALIASES.get(token, token).casefold()
            part_ids = by_gene.get(gene)
            if not part_ids:
                continue
            # Recognised by the catalog even if it is a cofactor_cycle part, which is not a step.
            recognised = True
            for part_id in part_ids:
                role = role_of[part_id]
                if role in found:
                    by_symbol.setdefault(role, set()).add(part_id)
        if recognised:
            reported = reported_designations(entry, by_gene)
            for role, part_ids in by_symbol.items():
                narrowed, designation, colliding = _narrow_by_designation(
                    part_ids, reported, designations
                )
                if colliding:
                    # THE SAFEGUARD, in the same shape as the organism clause's: a named refusal
                    # that says which parts collided, and leaves the role unfilled rather than
                    # quietly reverting to an ambiguous match over the cofactor the record named.
                    ambiguous_variants.append(
                        AmbiguousVariant(role, entry, designation or "", colliding)
                    )
                    continue
                found[role] |= narrowed
                entries_for[role].add(entry)
                resolved_by[role].add(BY_GENE_SYMBOL)
                if designation is not None:
                    resolved_by[role].add(BY_VARIANT_DESIGNATION)
            continue

        if names_a_role:
            role = _sole_step_role(tokens)
            organism = source_organism_of(entry)
            if role is not None and organism is not None:
                candidates = _parts_from(parts, role, organism)
                if len(candidates) == 1:
                    found[role].add(candidates[0])
                    entries_for[role].add(entry)
                    resolved_by[role].add(BY_SOURCE_ORGANISM)
                    continue
                if len(candidates) > 1:
                    # THE SAFEGUARD. Not a pick, not a silent fall-through to "vague record": a
                    # named refusal that says which parts collided, because the collision is the
                    # curation question and the reader is the one who can settle it.
                    ambiguous_sources.append(
                        AmbiguousSource(role, entry, organism, tuple(candidates))
                    )
                    continue
                # Zero candidates: the phrase parsed but the catalog has no such part. Treated as
                # a record the atlas cannot place, not as a catalog gap — the organism may be a
                # misparse of prose, and a miss asserted on a guess is the wrong direction of
                # error for a harness whose bias is pessimistic by design.

        # A role name with no enzyme behind it is a curation limit, not a catalog gap: the paper
        # said which step, not which protein. Kept apart from `unrecognised` because the two lead
        # to different verdicts and conflating them is what would inflate the figure.
        (role_named_only if names_a_role else unrecognised).append(entry)

    return Resolution(
        roles=tuple(
            RoleResolution(
                role=role,
                part_ids=tuple(sorted(found[role])),
                from_entries=tuple(sorted(entries_for[role])),
                resolved_by=tuple(sorted(resolved_by[role])),
            )
            for role in STEP_ORDER
        ),
        role_named_only=tuple(role_named_only),
        unrecognised=tuple(unrecognised),
        ambiguous_sources=tuple(ambiguous_sources),
        ambiguous_variants=tuple(ambiguous_variants),
    )


def _narrow_by_designation(
    part_ids: Collection[str],
    reported: Mapping[str, str],
    designations: Mapping[str, frozenset[str]],
) -> tuple[frozenset[str], str | None, tuple[str, ...]]:
    """``(parts to keep, the designation that narrowed them, the parts that collided)``.

    NARROWING ONLY, and that containment is the whole of why splitting a token is allowed here at
    all: this function is handed the parts a GENE SYMBOL already resolved to and can only return
    a subset of them. It cannot reach a part the symbol did not reach and cannot fill an empty
    role, so a misread designation can at worst refuse a match — never manufacture one.

    Three outcomes. Exactly one part carries a reported designation: narrow to it. Two or more do:
    refuse, and hand back both so the verdict can name them. None do — including the case where
    the record named no designation at all, which is the bare ``ilvC`` the ruling deliberately
    leaves alone: keep every candidate and stay ambiguous.
    """
    keep = frozenset(part_ids)
    if len(keep) < 2 or not reported:
        return keep, None, ()
    hits: set[str] = set()
    matched_keys: list[str] = []
    for key in sorted(reported):
        carrying = {part_id for part_id in keep if key in designations.get(part_id, frozenset())}
        if carrying:
            matched_keys.append(key)
            hits |= carrying
    if not hits:
        return keep, None, ()
    written_as = reported[matched_keys[0]]
    if len(hits) > 1:
        return keep, written_as, tuple(sorted(hits))
    return frozenset(hits), written_as, ()


def _parts_from(parts: Sequence[Part], role: str, organism: str) -> list[str]:
    """Every catalog part filling ``role`` whose ``source_organism`` is ``organism``.

    Sorted, and returned in full rather than as a count or a first hit: the caller refuses on a
    length of 2 and has to be able to NAME both. Recomputed per call — the uniqueness this rule
    leans on is a fact about the catalog as it is now, and caching it is how a resolution outlives
    the fact that justified it.
    """
    reported = _binomial(organism)
    if reported is None:  # unreachable via source_organism_of, which already parsed it
        return []
    matched: list[str] = []
    for part in parts:
        if part.step_role != role:
            continue
        catalog = _binomial(part.source_organism)
        if catalog is not None and _organisms_agree(reported, catalog):
            matched.append(part.id)
    return sorted(matched)


# ----------------------------------------------------------------------------- the verdict


@dataclass(frozen=True)
class ConfigurationVerdict:
    """What the harness decided about one configuration, and on which clause."""

    configuration: Configuration
    clause: str
    resolution: Resolution | None
    #: Ids of enumerated routes consistent with this configuration. Plural when a role was
    #: ambiguous; the count is reported rather than hidden behind "matched".
    route_ids: tuple[str, ...] = ()
    detail: str = ""

    @property
    def outcome(self) -> str:
        return _CLAUSE_BY_NAME[self.clause].outcome

    @property
    def organism_resolved_roles(self) -> tuple[str, ...]:
        """Roles this verdict resolved by role-plus-source-organism, not by a gene symbol.

        Non-empty on a `matched` verdict means the match rests, at those roles, on the weaker of
        the two identifications the rule allows. Exposed as data and not only as prose in
        `detail`, so a caller counting matches can count the two kinds apart.
        """
        return () if self.resolution is None else self.resolution.organism_resolved_roles

    @property
    def variant_resolved_roles(self) -> tuple[str, ...]:
        """Roles this verdict pinned by a variant designation narrowing a shared gene symbol.

        Exposed as data for the same reason as the organism kind: a reader of a recall figure has
        to be able to see how much of it rests on variant resolution, and a caller counting
        matches has to be able to count the kinds apart without parsing `detail`.
        """
        return () if self.resolution is None else self.resolution.variant_resolved_roles

    @property
    def partial(self) -> bool:
        """Every enzyme the record DID name resolved and agreed, but some role was left unnamed.

        Reported separately and never folded into recall — see the module docstring.

        A ``catalog_gap`` verdict is NOT partial even though routes agree on its filled roles: it
        named an enzyme (ADH7, yqhD) and that enzyme did not match. "Every named step agreed" has
        to mean every step the record named, or the softer figure is soft in a second, hidden way.
        """
        if self.clause == "matched":
            return True
        return self.clause == "under_specified" and bool(self.route_ids)


def _matching_routes(
    resolution: Resolution, strategy: str, routes: Sequence[Route]
) -> tuple[str, ...]:
    """Enumerated routes of this strategy that agree at every role the record filled.

    An unfilled role is skipped here — which is the loose rule, and is why this function is NOT
    the matching rule. :func:`classify` only accepts its answer as a MATCH when every role was
    filled; with a role unfilled the same answer becomes the `partial` figure, labelled as such.
    """
    wanted = {r.role: frozenset(r.part_ids) for r in resolution.roles if r.filled}

    def agrees(route: Route) -> bool:
        return route.strategy == strategy and all(
            step.part.id in wanted[step.step_role]
            for step in route.steps
            if step.step_role in wanted
        )

    return tuple(route.id for route in routes if agrees(route))


def classify(
    configuration: Configuration,
    parts: Sequence[Part],
    routes: Sequence[Route],
    *,
    chassis_organism_id: str | None,
) -> ConfigurationVerdict:
    """Apply :data:`MATCHING_RULE` to one configuration. First applicable clause wins."""
    strategy = configuration.compartment_strategy_id
    if strategy is None or strategy not in STRATEGY_PLANS:
        return ConfigurationVerdict(
            configuration,
            "strategy_not_enumerable",
            None,
            detail=f"compartment_strategy_id={strategy!r}",
        )
    if configuration.host_strain_id is None:
        return ConfigurationVerdict(configuration, "host_not_recorded", None)
    if chassis_organism_id is not None and configuration.host_organism_id != chassis_organism_id:
        host = configuration.host_organism_name or configuration.host_organism_id
        return ConfigurationVerdict(
            configuration,
            "host_outside_enumeration",
            None,
            detail=(
                f"host organism {host!r} is not the enumerated chassis organism "
                f"{chassis_organism_id!r}"
            ),
        )

    entries = enzyme_entries(configuration.description)
    if not entries:
        return ConfigurationVerdict(configuration, "no_enzyme_set_recorded", None)

    resolution = resolve_roles(entries, parts)
    route_ids = _matching_routes(resolution, strategy, routes)
    unfilled = resolution.unfilled_roles

    if not unfilled and route_ids:
        notes: list[str] = []
        ambiguous = resolution.ambiguous_roles
        if ambiguous:
            notes.append(
                f"ambiguous at {', '.join(ambiguous)} (the gene symbol does not distinguish the "
                f"variants)"
            )
        by_variant = resolution.variant_resolved_roles
        if by_variant:
            # The match kind, beside the match. A KARI pinned to one of four ilvC parts is a
            # statement about the cofactor, and the reader is entitled to see that it was the
            # designation and not the symbol that made it.
            notes.append(
                f"resolved BY VARIANT DESIGNATION at {', '.join(by_variant)} — a gene symbol "
                f"narrowed by a named variant, uniquely in the catalog"
            )
        by_organism = resolution.organism_resolved_roles
        if by_organism:
            # The match kind, beside the match and not in a footnote. A reader of 100% has to be
            # able to see how much of it rests on a role name plus an organism.
            notes.append(
                f"resolved BY SOURCE ORGANISM at {', '.join(by_organism)} — a role name plus a "
                f"source organism, uniquely in the catalog, not a gene symbol"
            )
        notes.append(
            f"{len(route_ids)} route agrees"
            if len(route_ids) == 1
            else f"{len(route_ids)} routes agree"
        )
        return ConfigurationVerdict(
            configuration, "matched", resolution, route_ids, "; ".join(notes)
        )

    if resolution.unrecognised:
        return ConfigurationVerdict(
            configuration,
            "catalog_gap",
            resolution,
            route_ids,
            detail=(
                f"unfilled: {', '.join(unfilled) or 'none'}; no part carries: "
                + "; ".join(f"{entry!r}" for entry in resolution.unrecognised)
            ),
        )

    blocking = tuple(a for a in resolution.ambiguous_sources if a.role in unfilled)
    if blocking:
        return ConfigurationVerdict(
            configuration,
            "source_organism_ambiguous",
            resolution,
            route_ids,
            detail=(
                f"unfilled: {', '.join(unfilled)}; " + "; ".join(a.describe() for a in blocking)
            ),
        )

    blocking_variants = tuple(a for a in resolution.ambiguous_variants if a.role in unfilled)
    if blocking_variants:
        return ConfigurationVerdict(
            configuration,
            "variant_designation_ambiguous",
            resolution,
            route_ids,
            detail=(
                f"unfilled: {', '.join(unfilled)}; "
                + "; ".join(a.describe() for a in blocking_variants)
            ),
        )

    return ConfigurationVerdict(
        configuration,
        "under_specified",
        resolution,
        route_ids,
        detail=(
            f"unfilled: {', '.join(unfilled)}"
            + (
                f"; named only by role: {', '.join(repr(e) for e in resolution.role_named_only)}"
                if resolution.role_named_only
                else ""
            )
            + (
                "; also, a source organism the catalog cannot narrow: "
                + "; ".join(a.describe() for a in resolution.ambiguous_sources)
                if resolution.ambiguous_sources
                else ""
            )
            + (
                "; also, a variant designation the catalog cannot narrow: "
                + "; ".join(a.describe() for a in resolution.ambiguous_variants)
                if resolution.ambiguous_variants
                else ""
            )
        ),
    )


# ------------------------------------------------------------------------------- the report


@dataclass(frozen=True)
class RecallReport:
    """The three numbers and the named misses. Never one number."""

    verdicts: tuple[ConfigurationVerdict, ...]
    #: What the harness compared against, so a figure cannot be read without its scope.
    route_count: int
    chassis_organism_id: str | None
    unrecognised_enzymes: tuple[str, ...] = field(default=())

    @property
    def matched(self) -> tuple[ConfigurationVerdict, ...]:
        return tuple(v for v in self.verdicts if v.outcome == "matched")

    @property
    def missed(self) -> tuple[ConfigurationVerdict, ...]:
        return tuple(v for v in self.verdicts if v.outcome == "missed")

    @property
    def not_evaluable(self) -> tuple[ConfigurationVerdict, ...]:
        return tuple(v for v in self.verdicts if v.outcome == "not_evaluable")

    @property
    def matched_by_source_organism(self) -> tuple[ConfigurationVerdict, ...]:
        """Matches resting, at one or more roles, on a role name plus a source organism.

        Reported beside the total for the same reason `coverage` is reported beside `recall`: the
        headline is true only in the company of the thing that qualifies it. A 100% built entirely
        out of this kind of identification is a different claim from a 100% built out of gene
        symbols, and nothing else in the output would say so.
        """
        return tuple(v for v in self.matched if v.organism_resolved_roles)

    @property
    def matched_by_variant_designation(self) -> tuple[ConfigurationVerdict, ...]:
        """Matches resting, at one or more roles, on a variant designation narrowing a symbol.

        A different kind from a bare gene symbol rather than a weaker one — it is the NARROWER
        identification, and it is the only one that can say which of four ilvC parts a build used.
        Counted apart all the same: a figure that rests on reading `6E6` out of a part id is
        resting on something a reader should be told about, and the three counts together are
        what let anyone see what a recall figure is made of.
        """
        return tuple(v for v in self.matched if v.variant_resolved_roles)

    @property
    def matched_by_gene_symbol(self) -> tuple[ConfigurationVerdict, ...]:
        """Matches in which every role was pinned by a gene symbol ALONE — nothing qualified it.

        The complement of the other two, which is why it is defined by their absence: those two
        can overlap (one configuration may name an organism at one role and a variant at another)
        and a reader adding three overlapping counts would get a number larger than the total.
        """
        return tuple(
            v
            for v in self.matched
            if not v.organism_resolved_roles and not v.variant_resolved_roles
        )

    @property
    def evaluable(self) -> int:
        return len(self.matched) + len(self.missed)

    @property
    def recall(self) -> float | None:
        """matched / evaluable, or None when nothing can be judged.

        None, not 0.0 and not 1.0. With `pathway_configuration` empty there is no evidence either
        way, and both constants would be a claim: 0.0 that the enumerator failed, 1.0 that it
        succeeded. This is the same rule the enumerator applies to `score_evidence`.
        """
        return None if self.evaluable == 0 else len(self.matched) / self.evaluable

    @property
    def coverage(self) -> float | None:
        """evaluable / total — what fraction of the literature the figure above speaks for."""
        return None if not self.verdicts else self.evaluable / len(self.verdicts)

    @property
    def partial(self) -> float | None:
        """What recall would be if a configuration naming only some of its enzymes counted.

        Always >= recall. Printed beside it and labelled, because it is the number somebody will
        want and the number that must never be called recall.
        """
        if not self.verdicts:
            return None
        return sum(1 for v in self.verdicts if v.partial) / len(self.verdicts)


def recall_report(
    configurations: Sequence[Configuration],
    parts: Sequence[Part],
    routes: Sequence[Route],
    *,
    chassis_organism_id: str | None,
) -> RecallReport:
    """Classify every configuration and collect what the catalog did not recognise."""
    verdicts = tuple(
        classify(c, parts, routes, chassis_organism_id=chassis_organism_id) for c in configurations
    )
    unrecognised: set[str] = set()
    for verdict in verdicts:
        if verdict.resolution is not None:
            unrecognised.update(verdict.resolution.unrecognised)
    return RecallReport(
        verdicts=verdicts,
        route_count=len(routes),
        chassis_organism_id=chassis_organism_id,
        unrecognised_enzymes=tuple(sorted(unrecognised)),
    )


def _fraction(value: float | None) -> str:
    return "not measurable" if value is None else f"{value:.0%}"


def describe_report(report: RecallReport) -> tuple[str, ...]:
    """The report as lines. Formatting lives here so a test can read the same text a reader does."""
    lines: list[str] = [
        f"{len(report.verdicts)} published configuration(s) against {report.route_count} "
        f"enumerated routes",
        "",
        f"  recall    {_fraction(report.recall):>14}   "
        f"{len(report.matched)}/{report.evaluable} of the configurations that CAN be judged",
        f"  coverage  {_fraction(report.coverage):>14}   "
        f"{report.evaluable}/{len(report.verdicts)} could be judged at all",
        f"  partial   {_fraction(report.partial):>14}   "
        f"every NAMED step agreed — NOT recall, and never to be quoted as it",
    ]
    if report.matched:
        # The match-kind breakdown, immediately under the figure it qualifies. Printed whenever
        # anything matched, including when the weaker count is 0 — a reader has to be able to tell
        # "none of it rests on that" from "nobody said".
        lines.append(
            f"  of which  {len(report.matched_by_gene_symbol):>14}   "
            f"matched by gene symbol alone, "
            f"{len(report.matched_by_variant_designation)} by a variant designation, and "
            f"{len(report.matched_by_source_organism)} by a role name plus a source organism "
            f"(the last two are qualified names, not bare ones — see `--rule`)"
        )
    if not report.verdicts:
        lines += [
            "",
            "`pathway_configuration` is empty, so the recall clause of PLAN.md phase 3 CANNOT BE",
            "EVALUATED. That is the honest answer and it is not the same as 0% or 100%. The",
            "harness, the rule and the CLI are in place; they are waiting on phase 1's rows.",
        ]
        return tuple(lines)

    if report.matched:
        lines += ["", "matched:"]
        for verdict in report.matched:
            lines.append(f"  {verdict.configuration.id}  {verdict.configuration.name}")
            lines.append(f"      {verdict.detail}")
            lines.append(f"      first route: {verdict.route_ids[0]}")
    if report.missed:
        lines += ["", "MISSED — the enumerator cannot express these builds:"]
        for verdict in report.missed:
            lines.append(f"  {verdict.configuration.id}  {verdict.configuration.name}")
            lines.append(f"      [{verdict.clause}] {verdict.detail}")
    if report.not_evaluable:
        lines += ["", "not evaluable — neither a hit nor a miss, and named rather than dropped:"]
        for verdict in report.not_evaluable:
            lines.append(f"  {verdict.configuration.id}  {verdict.configuration.name}")
            lines.append(
                f"      [{verdict.clause}] {verdict.detail or _CLAUSE_BY_NAME[verdict.clause].text}"
            )
    if report.unrecognised_enzymes:
        lines += [
            "",
            "enzymes named by published builds that no part in the catalog carries:",
            "  " + "; ".join(repr(e) for e in report.unrecognised_enzymes),
            "  Some are real catalog gaps (curate a part). Some are prose, or enzymes outside the",
            "  five step roles entirely (transaminases, competing routes). Triaging them is",
            "  curation, and it is the worklist this whole harness exists to produce.",
        ]
    return tuple(lines)
