# Which strain was each `pathway_configuration` built in — read out of the papers

2026-09-21. Draft. **Nothing here has been written.** No row in `data/`, no row in the database,
no `fermdb curate accept / reject / promote`, no `confidence` value, no `verified` flag. The
machine-readable form is `host_resolution.yaml` beside this file.

`pathway_configuration` has 0 rows. It is phase 1's headline deliverable and phase 3's acceptance
test measures route-enumerator recall against it, so phase 3 has never been testable. The 14
accepted `pathway_configurations` proposals cannot be promoted because `promote.py::_plan_configuration`
refuses to guess `host_strain_id` and `product_id` — **the extraction schema has no host field.**
This document supplies the two missing fields from the papers themselves.

## Method, and what "verified" means here

Each paper's stored full text was loaded through the repo's own
`fermdb.extract.harness.load_source_text` — no PDF was re-parsed. Every quote below was **sliced
straight out of that text** at the offsets given, and then re-checked independently with
`fermdb.llm.validate.verify_span`, which does exact comparison with no whitespace normalization
and no fuzzy matching.

**23 of 23 distinct spans re-resolved exact. 0 absent, 0 spliced.** (31 of 31 counting the
supporting spans that appear under more than one configuration.) The offsets are in the same
coordinate system the stored proposals use, so a quote here and a quote in a payload are directly
comparable.

Two authoring mistakes were caught by the verifier on the first pass and repaired against the
source rather than accepted — an anchor that matched twice (a body sentence and a figure legend),
and one that matched zero times because of a PDF ligature. That is the behaviour that makes the
23 mean anything.

Host and product were then checked against the live tables: every `host_strain_id` below is an
existing `strain.id`, every `product_id` an existing `product.id`, every `pathway_id` an existing
`pathway.id`.

## There are 14 proposals, not 13

The brief expected 13. The queue holds 14 across the same 4 publications. The extra one is not a
duplicate defect: `a182c009` (SHy61) and `a55bc030` (SHy62) are byte-identical apart from
`strain_name_as_reported` and share one span, because they are **the same plasmid in two different
backgrounds** — which is two configurations by host, exactly as it should be.

## The verdict

| # | task (tail) | publication | host strain | product | recommendation |
|---|---|---|---|---|---|
| 1 | `…4622e91b` | cels 2019 | `gln3d-gln3d-homozygous-diploid-by4743-strain` | isobutanol | **promote** |
| 2 | `…40e7afa2` | cels 2019 | `gln3d-gln3d-homozygous-diploid-by4743-strain` | isobutanol | **promote** |
| 3 | `…6d83c72d` | jbiotec 2022 | `e-coli-hm501` | isobutanol | **promote pending vocabulary** |
| 4 | `…dcddee9ec` | meteno 2016 | **not established** | **not established** | reject |
| 5 | `…6a1f5f98` | ymben 2017 | `shy48` | isobutanol | **promote** |
| 6 | `…5f5f791f` | ymben 2017 | `shy34` | isobutanol | **promote** |
| 7 | `…44fe2470` | ymben 2017 | **not established** | isobutanol | reject |
| 8 | `…69ff742d` | ymben 2017 | **not established** | isobutanol | reject |
| 9 | `…e67a5209a9` | ymben 2017 | **not established** | isobutanol | reject |
| 10 | `…c845355352` | ymben 2017 | `shy61` (established) | isobutanol | reject — strategy `unknown` |
| 11 | `…9be430af415` | ymben 2017 | `shy62` (established) | isobutanol | reject — strategy `unknown` |
| 12 | `…54527d2c47` | ymben 2017 | `shy48` (by titer, two loci) | isobutanol | reject — duplicate of #5 |
| 13 | `…802b555c96e` | ymben 2017 | **not established** | isobutanol | reject |
| 14 | `…140eb80a2b` | ymben 2017 | **not established** | isobutanol | reject |

**4 promote now, 1 promote after a one-row vocabulary addition, 9 reject.** The four were dry-run
through `plan_promotion` with these values supplied: **zero missing fields, zero blockers** on all
four. The fifth comes back missing exactly `compartment_strategy_id`, as predicted below.

---

## 1–2. Cell Systems 2019 — the GLN3 tolerance paper

*Critical Roles of the Pentose Phosphate Pathway and GLN3 in Isobutanol-Specific Tolerance in Yeast*

One sentence carries both configurations and names the host in the middle of it:

> we overexpressed five genes in the isobutanol biosynthetic pathway, ILV2, ILV3, ILV5, and ADH7
> from *S. cerevisiae* and **2-ketoacid decarboxylase (KDC) from *Lactococcus lactis* in the gln3D
> strain in their native locations (mitochondria and cytosol)** *or targeted exclusively to the
> mitochondria*

The bold half is proposal 1's span (`A_native_split`, [35628, 35755)); the italic half is proposal
2's (`C_mitochondrial_ehrlich`, [35690, 35799)). The two proposals are a correct split of one
sentence, not a duplicate.

"the gln3D strain" is a generic label, though, and the very next sentence names the actual
background — and names it for **both** configurations at once:

> We introduced the native or mitochondrial isobutanol biosynthetic pathways into a
> **gln3D/gln3D homozygous diploid BY4743 strain** using a 2 μ plasmid — [35874, 36020)

That is why both rows take `YAA:STRAIN:gln3d-gln3d-homozygous-diploid-by4743-strain` rather than
the looser `YAA:STRAIN:gln3d-strain` the payloads report. Figure 6A's numbers are that diploid's:
306 ± 4 mg/L against 63 ± 7 mg/L for wild-type BY4743 carrying the same plasmid.

**One thing a curator should decide.** The *natively localized* configuration was **also** built in
a haploid — "The BY4741 gln3D strain harboring pJA184" [36851, 36891) — so configuration 1 has two
published hosts and arguably deserves two rows. The mitochondrial configuration does not: the
haploid sentence is explicitly about "strains overexpressing the natively localized isobutanol
pathway", so it cannot be borrowed for row 2.

**A caveat that does not change the host.** The paper reports no titer for the mitochondrial
build — *"isobutanol titers did not improve in strains harboring the mitochondrial pathway (data
not shown)"*. It is a real published configuration with an absent measurement, which is a
different thing from a configuration that was not built.

## 3. J. Biotechnology 2022 — the xylose-regulator paper

This is the cleanest host determination in the set, because the paper says it in the schema's own
words:

> **The isobutanol producing strain *E. coli* HM501 was used in this work as a host strain**
> — [8398, 8483)

The payload's five enzymes are exactly HM501's introduced set:

> …and introduce five genes ( alsS, ilvC, ilvD, kivD , and yqhD ) that positively regulate
> isobutanol production — [15549, 15688)

Product is isobutanol, measured in g/L throughout (5.18, 1.76, 2.79…).

**And it still cannot be promoted, for a reason that is a finding rather than a failure.** Its
`compartment_strategy` is `"NA"`, and `NA` is not one of the five seeded `compartment_strategy`
rows — all five (`A_native_split`, `B_cytosolic_relocalization`, `C_mitochondrial_ehrlich`,
`D_alternative_compartment`, `E_mtdna_encoded`) presuppose a eukaryotic compartment choice. *E.
coli* has no compartment choice to make, so `"NA"` is the honest answer to a question the
vocabulary should not have asked. PLAN.md phase 1 asks for *"every published microbial isobutanol
production strain, **any host**"* — so a prokaryotic / no-compartmentalization strategy row is
implied by the plan's own scope and is missing. **That is a one-row data change, and it converts
the best-evidenced host in this whole set into a promotable configuration.**

Two smaller notes. `pathway_id` is left null: the only isobutanol pathway row carries evidence
saying *"compartment assignment follows the native S. cerevisiae localisation"*, so attaching an
*E. coli* build to it is a scope decision, not a reading of this paper. And the strain table holds
**two rows for the same organism** — `YAA:STRAIN:e-coli-hm501` and `YAA:STRAIN:hm501`. This draft
uses the one the host sentence names verbatim; they should be merged.

## 4. Metabolic Engineering Communications 2016 — the valine assimilation paper

*Mitochondrial targeting increases specific activity of a heterologous valine assimilation pathway*

**This is the one the brief warned about, and it fails on both fields.**

**The host is not establishable, because the paper names two in one sentence:**

> Constructed plasmids were expressed in haploid *S. cerevisiae* strains **CKY263 and BJ5464**
> after transformation — [11337, 11444)

And it is worse than an ambiguity, because the two hosts carry different parts of this proposal.
The span the proposal quotes ("the mt leader peptide appeared to direct expression towards the
mitochondria of the cell") sits in the confocal localization work, which is CKY263 —

> *S. cerevisiae* CKY263 cells were induced for 24 h with galactose before being stained
> — [18436, 18520)

— while the **assembled five-gene BCKAD+ACD set the payload actually lists** was assayed in BJ5464:

> Experiments performed in triplicate in BJ5464 [p(mt)ACD1 p(mt)BCKAD4 p(mt)CoA2] at 24 h
> — [21764, 21851)

Picking either one would attach the configuration to a host that carried only half of it. So:
`host_strain_id: null`, and the reason is on the record.

**The product is not isobutanol, and is not establishable at all.** This route stops at
isobutyryl-CoA → methacrylyl-CoA. No alcohol is made and no titer is measured anywhere in the
paper; the assays are ACD and BCKAD **specific activity**. The paper's own claim about what the
route yields is:

> bacterial valine catabolism may be used in yeast to produce **precursors for** isobutanol and
> biomonomer production — [23716, 23827)

Defaulting this to `YAA:PRODUCT:isobutanol` is precisely the error `_plan_configuration`'s
`product_id` refusal was written to prevent — *"defaulting it to isobutanol because this is an
isobutanol atlas would file any other build as an isobutanol one."* **Decision D12 and question 1
of report §7 are confirmed here from the text, not from the payload's warning note.** The
`C_mitochondrial_ehrlich` label is also wrong on its face: these are bacterial valine
*degradation* enzymes from *P. aeruginosa*, not the Ehrlich pathway.

## 5–6. Metabolic Engineering 2017, the two that carry real builds

*Uncovering the role of branched-chain amino acid transaminases in S. cerevisiae isobutanol biosynthesis*

The chassis for everything in this paper is stated once —

> Single 2μ plasmids bearing the desired genes were transformed into CEN.PK2-1C — [28837, 28913)

— but the chassis is not the host of a configuration; the engineered derivative is, and the paper
names those derivatives at the locus where each is built.

**#6, SHy34** — `C_mitochondrial_ehrlich`, mitochondrial ARO10 + LlAdhA(RE1) via the Cox4
presequence, **without** ILV overexpression:

> The bat1Δ strain overexpressing only ARO10 and LlAdhA RE1 localized to mitochondria **(SHy34)**
> produces 998 ± 7 mg/L isobutanol in the absence of valine — [42972, 43123)

**#5, SHy48** — the same, **plus** the ILV genes. The paper's best producer:

> When we also overexpress the ILV genes **(SHy48)** the isobutanol titer increases to
> 1245 ± 33 mg/L — [43206, 43303)

These two are genuinely distinct configurations — the paper contrasts them directly — and each
sentence names its strain, its localization and its titer together. They are the strongest rows
available and the first two the table should hold.

## 7, 8, 13, 14. Four that the paper states generically — host correctly `null`

**#13 (`…802b555c96e`, ValC-dependent) and #14 (`…140eb80a2b`, KIVC-dependent)** come from the
Fig. 2 schematic paragraph, whose subject is the **native** architecture of the organism, not any
constructed strain: *"Isobutanol production from glucose in the naturally compartmentalized
upstream and downstream pathways in Saccharomyces cerevisiae can proceed through two possible
pathways."* The spans are "we call this the ValC-dependent pathway" [27597, 27636) and
"mitochondrial KIV is exported to the cytosol," [27665, 27710). No strain is named anywhere in
that paragraph.

**#8 (`…69ff742d`)** is the *shared tail* of those same two routes — "In both pathways, KDC and
ADH enzymes convert KIV to isobutanol in the cytosol" [27850, 27928) — so it duplicates the half
#13 and #14 have in common and adds nothing of its own.

**#7 (`…44fe2470`)** is a Discussion strategy statement — "compartmentalization of the complete
isobutanol pathway in mitochondria" [57627, 57700) — with **no `strain_name_as_reported` and no
`enzymes_as_reported` key at all**. It is the generic form of what SHy34 and SHy48 already record
concretely.

All four: `host_strain_id: null`, reason *the paper describes this configuration in general terms;
no single host named at this locus*. Recommendation **reject** as `pathway_configuration` rows.

**But #13 and #14 should not simply vanish.** The ValC-dependent / KIVC-dependent split is this
paper's central novel claim and is exactly the kind of route topology phase 3's enumerator reasons
over. It belongs in `pathway` / route knowledge, not in a host-bound configuration row — and both
carriers are unidentified genes, which is a standing `knowledge_gap`.

## 9. The degenerate one

**`…e67a5209a9`** has `enzymes_as_reported: []` and `strain_name_as_reported: "bat1Δ strains"` —
plural and collective, covering SHy16, SHy24, SHy34, SHy48 and SHy55 at different points of the
paper. Its span is the Discussion's self-summary:

> only a BAT1 deletion and the mitochondrial isobutanol pathway in fermentation media lacking
> valine — [59078, 59176)

That is a claim about the *study*, not a configuration. A row with no enzymes and a collective
host records nothing. **Reject.**

(Note in passing: `YAA:STRAIN:bat1-strains` exists as a promoted strain row. It is the same
collective-label artifact one level down and should not be used as a host by anything.)

## 10–11. Host established, strategy `unknown` — reject as proposed, but the fix is one field

SHy61 and SHy62 are the two hosts of plasmid pSH46:

> we transformed ilv6Δ and bat1Δ ilv6Δ strains with a 2μ plasmid (pSH46) containing ILV2, ILV3,
> ILV5, and a valine-insensitive ILV6 mutant — [38974, 39098)
>
> The ilv6Δ strain overexpressing these four genes **(SHy61)** produces 502 ± 5 mg/L isobutanol in
> the absence of valine — [39206, 39320)
>
> expressing ILV6 V90D/L91F in the bat1Δ ilv6Δ background **(SHy62)** restores isobutanol titers in
> the absence of valine to 655 ± 10 mg/L — [39421, 39555)

**Both hosts are established beyond doubt.** What kills them is `compartment_strategy: "unknown"`,
which is not one of the five seeded rows, so the promoter refuses — and rightly, because a
configuration whose strategy is unknown records nothing that the `strain` and `modification` rows
do not already hold.

**The curator fix is cheap and I am deliberately not taking it.** These builds overexpress only
the upstream ILV enzymes and rely on the native cytosolic KDC/ADH, which is `A_native_split` by
the vocabulary's own definition and by the paper's own Fig. 2. Editing that one field turns two
rejects into two promotable rows with hosts already resolved. Editing a payload is a curator act.

## 12. A duplicate, and an honest note about how its host was identified

**`…54527d2c47`** is the Discussion restating the SHy48 build:

> The best isobutanol producing strain in this study, containing a BAT1 deletion and overexpressing
> ILV2, ILV3, ILV5, along with ARO10 and LlAdhA RE1 in the mitochondria can reach a titer of
> 1.25 g/L — [57772, 57972)

**That locus names no strain.** SHy48 is identified by matching the titer across two loci —
1.25 g/L here against 1245 ± 33 mg/L in the Results, where SHy48 is named and is the paper's best
producer. That is a sound identification, but it is a two-locus inference, not a sentence that
names a host. Rather than stretch it, the entry records the reasoning and recommends **reject as a
duplicate of #5**, which names SHy48 outright.

One thing to carry across if a curator merges rather than rejects: **this payload's enzyme list is
the better one** (`ILV2, ILV3, ILV5, ARO10, LlAdhA`) — #5's is `ARO10, LlAdhA RE1, "ILV genes"`.
Keep this enzyme list and #5's strain-naming span.

---

## What this unblocks, and what it does not

Promoting the four clears `pathway_configuration` from 0 and makes **phase 3's acceptance test
runnable for the first time in the project's life.** Four rows is a small measuring stick, and it
is a real one: two mitochondrial-Ehrlich builds that differ by exactly one intervention
(SHy34 / SHy48, 998 vs 1245 mg/L), and a native-split / mitochondrial pair in the same GLN3
background from a different lab. That is a recall test with contrast in it, not four copies of one
thing.

What it does not do is fix the reason nine were rejected. **Seven of the nine failed on fields the
extraction schema does not ask for or does not constrain** — no host field, and a
`compartment_strategy` that accepts free text (`"unknown"`, `"NA"`) instead of the seeded
vocabulary the promoter validates against. Adding a host field to the extraction schema, and
constraining `compartment_strategy` to the vocabulary at proposal time, would have turned most of
this document into a no-op. That is the same class of gap as the missing `part_expression_records`
section in report §3: **the gap has moved upstream, into what the extractor is asked for.**

### The four curator decisions this draft hands over

1. **Add a prokaryotic / no-compartmentalization `compartment_strategy` row.** One row, and the
   best-evidenced host in the set (`E. coli` HM501) becomes promotable. PLAN.md's "any host" scope
   already implies it.
2. **Edit `compartment_strategy` on SHy61 and SHy62 from `unknown` to `A_native_split`** — or
   decide the reading is mine and not the paper's, and leave them rejected.
3. **Decide whether configuration 1 gets one row or two** — the natively localized pathway has two
   published hosts in the Cell Systems paper (the BY4743 diploid and the BY4741 haploid).
4. **Merge the two `E. coli` HM501 strain rows**, and stop `YAA:STRAIN:bat1-strains` being usable
   as a host.
