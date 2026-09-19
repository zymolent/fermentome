# The mitochondrial programme

Written because mitochondrial genome engineering was chosen as a **research goal**, with
biolistic/ρ⁰ capability available. That changes it from something the atlas models and
downweights into something the atlas must support properly.

⚠ marks a claim from background knowledge rather than a source read in this session. This document
has a higher ⚠ density than the rest of the plan and a lower tolerance for being wrong, because it
will inform construct design. **Verify every ⚠ in section 3 against primary literature before
building anything.**

---

## 1. The strategic case, stated honestly

### Why mtDNA expression is an interesting idea for this pathway

The valine branch (Ilv2/Ilv6 → Ilv5 → Ilv3) already runs in the mitochondrial matrix, so
2-ketoisovalerate is produced there ⚠. Finishing the route in the matrix — a ketoacid
decarboxylase and an alcohol dehydrogenase acting where the substrate already is — avoids the
unidentified 2-KIV export step entirely (`ISOBUTANOL_PROGRAM.md` §5).

Two arguments favour doing that from mtDNA rather than from the nucleus:

1. **No import dependency.** A nuclear gene with a targeting sequence must be imported through
   TOM/TIM, and import efficiency is finite, saturable and rarely measured. A gene transcribed and
   translated inside the matrix has no import step.
2. **Copy number.** mtDNA is present at roughly 50–200 copies per cell in nucleoids ⚠, which is a
   gene dosage a single nuclear integration cannot match.

### Why it is nonetheless the second experiment, not the first

**Strategy C — nuclear genes with mitochondrial targeting sequences — tests the same biological
hypothesis at a small fraction of the cost.** Both ask "does finishing the route in the matrix
improve isobutanol?" If C fails for reasons unrelated to import, E fails too. If C succeeds,
you may not need E. And C has published precedent for this exact pathway ⚠, while E has none.

E becomes justified precisely when **C works but is import-limited** — which is a measurable
condition, not a guess. That is why `ISOBUTANOL_PROGRAM.md` makes `verification_method` and
`import_efficiency_reported` mandatory fields on every localization record: those fields are what
tell you whether to escalate to mtDNA.

> **Recommended sequencing: run strategy C first, instrumented to measure import. Escalate to E
> only on evidence of an import ceiling.** The atlas should be built to produce that evidence.

---

## 2. The four constraints that decide feasibility

These are the things that make mtDNA engineering different in kind, not merely in difficulty.
Each becomes a schema field, because each can independently kill a construct.

### 2.1 Translational activators — the binding constraint ⚠

This is the one most often missed, and it is the reason you cannot simply insert an ORF into
mtDNA.

Yeast mitochondrial mRNAs are **not** translated generically. Each requires specific,
nuclear-encoded translational activator proteins that recognize its own 5′ untranslated leader ⚠:

| mtDNA gene | activators reported ⚠ |
|---|---|
| *COX1* | Pet309, Mss51 |
| *COX2* | Pet111 |
| *COX3* | Pet494, Pet54, Pet122 |
| *COB* | Cbs1, Cbs2 |
| *ATP6* | Atp22 |
| *ATP9* | Aep1, Aep2 |

**Consequence for design:** a heterologous ORF must be placed behind an existing mitochondrial
gene's 5′ UTR, at that gene's locus, so the resident activator drives it. This is exactly how
mitochondrial reporter constructs are built — the recoded *ARG8ᵐ* marker is inserted at the *COX3*
or *COX2* locus and uses those genes' leaders ⚠.

It also means **inserting a gene costs you the gene whose UTR you borrowed**, unless the displaced
gene is re-provided. Taking the *COX2* locus costs Cox2 and therefore respiration, unless *COX2*
is relocated. That trade is a first-class field:

```
mtdna_insertion
  locus                 COX2 | COX3 | COB | intergenic | ...
  utr_source            which gene's 5' leader drives it
  activator_required    Pet111 | Pet494/54/122 | ...
  displaced_gene        NULL | COX2 | COX3 | ...
  respiration_retained  bool
  rescue_strategy       none | nuclear_allotopic_copy | second_locus | ...
```

### 2.2 Recoding for translation table 3

Covered in `PLAN.md` B.6 point 3 and enforced in the schema. In summary: `UGA` = Trp, `AUA` = Met,
`CUN` = **Thr not Leu**, `CGA`/`CGC` absent ⚠. Any ORF placed into mtDNA must be recoded; a
leucine-rich sequence is the dangerous case because it mistranslates extensively while still
looking like a sensible gene.

A second, softer constraint: yeast mtDNA is strongly AT-rich (~80%+ ⚠), and the mitochondrial
translation system's codon usage reflects that. Recoding should target mitochondrial codon usage,
not merely legal codons.

**Deliverable, phase 0:** a codon recoder with a validation test suite — table 1 → table 3 and
back, refusing any sequence that would introduce an internal stop or an unassigned codon, and
reporting the AT content and rare-codon profile of the output. This is small, concrete, and
immediately useful at the bench.

### 2.3 Soluble matrix proteins from mtDNA — precedent exists, but it is thin ⚠

Mitochondrial translation is largely membrane-associated: most mtDNA-encoded products are
hydrophobic inner-membrane subunits, inserted co-translationally via Oxa1 ⚠. A soluble matrix
enzyme is the unusual case.

The encouraging precedent is **Arg8ᵐ** — acetylornithine aminotransferase, a soluble matrix
metabolic enzyme, expressed functionally from mtDNA and used routinely as a marker ⚠. That is
genuine proof of principle that a soluble metabolic enzyme can be made from mtDNA and fold and
function in the matrix.

It is one precedent, for one enzyme. A ketoacid decarboxylase (TPP-dependent, typically
homotetrameric ⚠) and an alcohol dehydrogenase (often Zn-dependent, oligomeric ⚠) are larger and
have cofactor and assembly requirements Arg8 does not. Whether the matrix supports their folding,
cofactor loading and oligomerization is **unknown and is the central scientific risk of this
programme.**

The atlas records this as a `knowledge_gap` of kind `never_attempted`, with the Arg8ᵐ precedent
attached as the nearest supporting evidence — which is exactly the shape of an honest research
question.

### 2.4 Transformation, homoplasmy and stability

The established route ⚠:

```
construct (recoded, with borrowed 5' UTR, plus a mitochondrial marker)
  → biolistic bombardment of a ρ⁰ recipient
  → synthetic ρ⁻ clone carrying the construct
  → mate to a ρ⁺ strain, karyogamy-deficient (kar1-1) so cytoplasms mix but nuclei do not
  → homologous recombination into resident mtDNA
  → select and screen for homoplasmy by mitotic segregation
```

Each step is a field: `technique`, `recipient_state`, `marker`, `recoded_for_table_3`,
`heteroplasmy_achieved`, `generations_to_homoplasmy`, `stability_tested`.

Two properties to design around: efficiency is low, so throughput is a handful of constructs
rather than a library; and mtDNA is recombinogenic and AT-rich, so **insert stability must be
tested over generations rather than assumed**, especially under non-selective conditions — which
production conditions usually are.

Selection markers ⚠: complementation of a *mit⁻* lesion restoring growth on a non-fermentable
carbon source (the classical *COX2*/*COX3* approach), or *ARG8ᵐ* complementing a nuclear *arg8Δ*.
Note the tension with 2.1 — the marker also needs a locus and a leader.

---

## 3. What the atlas must hold for this programme

Beyond the isobutanol corpus, a bounded mitochondrial-genetics corpus. It is small and
well-defined, which is why adding it is affordable even in a compressed plan.

| content | why | rough size ⚠ |
|---|---|---|
| mtDNA reference sequence + annotation under table 3 | Construct design; locus and UTR coordinates | 1 genome |
| Translational activator map: gene → leader → activator | 2.1; determines where an insert can go | ~10 loci |
| Transformation method records: technique, recipient, efficiency, lab | Feasibility, and who to ask | ~30–60 papers |
| Marker systems, with what each costs | Selection design | ~10 |
| Precedents for heterologous or recoded ORFs in yeast mtDNA | The evidence base for 2.3 — expect it to be thin, and that is itself the finding | ~10–25 |
| Stability and heteroplasmy data | Whether a construct survives production | ~10 |
| Allotopic expression attempts (mtDNA genes moved to the nucleus) | The mirror-image problem; informative about recoding and import | ~20 |
| ρ⁰/ρ⁻ physiology: what a cell loses | Chassis consequences | ~10 |

**Explicitly excluded**, to keep this bounded: mitochondrial disease models, human mtDNA editing
beyond technique transfer, mitophagy and dynamics, and mitochondrial biogenesis regulation. Each
is a large field and none advances a construct.

---

## 4. Strategy E, added to the configuration model

`ISOBUTANOL_PROGRAM.md` §2 gains a fifth row:

| strategy | what is done | solves | costs |
|---|---|---|---|
| **E. mtDNA-encoded Ehrlich pathway** | Recoded KDC and/or ADH inserted into mtDNA behind a resident 5′ UTR | No import dependency; high gene dosage; route fully co-localized with 2-KIV | Everything in section 2: activator/locus constraint, displaced gene, recoding, unproven for these enzyme classes, low-throughput construction, stability |

Its `feasibility_rating` is `frontier`, and — because the lab has the capability — the rating is
qualified by `available_here: true`, so the route ranker shows it as reachable rather than
theoretical while still costing it correctly. Those are two different facts and the schema keeps
them apart: *is this technique possible at all* and *is it possible for you*.

### The comparison the atlas should make easy

```
Strategy C  nuclear KDC+ADH, matrix-targeted    │  Strategy E  mtDNA-encoded KDC+ADH
─────────────────────────────────────────────────┼──────────────────────────────────────
precedent for isobutanol         yes ⚠           │  none
construction time                days–weeks      │  months
throughput                       many variants   │  few
import dependency                yes             │  no
gene dosage                      1–n integrations│  ~50–200 copies ⚠
respiration cost                 none            │  possible, locus-dependent
recoding required                no              │  yes
folding/assembly in matrix       demonstrated ⚠  │  unknown for these enzymes
```

The row that should drive the decision is the last one crossed with the first: C answers the
biology, E answers the delivery. **Do not use E to test a hypothesis C can test.**

---

## 5. The decision this programme should reach

The atlas is not being built to justify mtDNA engineering. It is being built to tell you whether
it is warranted. The specific outputs that answer that:

1. **Is matrix co-localization beneficial at all?** From strategy C evidence across the corpus.
   If no, E is moot regardless of capability.
2. **Is strategy C import-limited?** From localization verification and import efficiency
   records. This is the trigger condition for E.
3. **Which locus and leader can carry the insert, and what does it displace?** From the
   activator map. This is construct design, and it is the gating practical question.
4. **Has any soluble heterologous enzyme of this class been made from mtDNA?** From the
   precedents table. Expect a thin answer; the size of the gap is the size of the risk.
5. **Does the insert stay?** From stability data — and if the corpus cannot answer it, that is a
   required experiment, not an assumption.

A defensible conclusion at the end of phase 3 could equally be *"strategy C first, E held in
reserve pending an import measurement"* or *"E is worth attempting now because C is documented as
import-limited"*. Both are wins. The failure mode the atlas exists to prevent is starting a
twelve-month mtDNA campaign because it sounded compelling, without checking whether the cheap
experiment already answers the question.
