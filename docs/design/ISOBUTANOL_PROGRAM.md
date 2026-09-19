# The isobutanol program

The scientific core of the atlas, in the detail PLAN.md sections G.5–G.8 only contract for.

Goal: engineer *S. cerevisiae* for isobutanol production, and use the atlas to choose the route.
Everything here serves route selection. ⚠ marks a claim carried from background knowledge rather
than read from a source in this session — each must be verified before it enters the database.

---

## 1. The route, stated as the database will hold it

```
                       CYTOSOL                    │        MITOCHONDRIAL MATRIX
                                                  │        genetic code: NCBI table 3
  glucose → … glycolysis … → pyruvate ────────────┼──── MPC ──→ pyruvate
                    │                             │                │
     ┌──────────────┼───────────────┐             │        ILV2 / ILV6   [TPP]
     │              │               │             │                ↓
  PDC1/5/6      PYC1/PYC2        (biomass)        │          2-acetolactate
  [competing]   [competing]                       │                ↓
     ↓                                            │        ILV5   [NADPH]  ←── cofactor mismatch
  acetaldehyde                                    │                ↓
     ↓ ADH1 [NADH]                                │        2,3-dihydroxyisovalerate
  ETHANOL  ← the sink to defeat                   │                ↓
                                                  │        ILV3   [Fe-S, O₂-labile ⚠]
                                                  │                ↓
                                                  │        2-KETOISOVALERATE
                                                  │            ╱      ╲
                                    ??? carrier ──┼───────────╱        ╲
                                    UNKNOWN ⚠     │      BAT1        LEU4/LEU9
                                                  │    [competing]   [competing]
     2-ketoisovalerate                            │       ↓              ↓
          ↓ ARO10 / PDC1/5/6 / kivD               │     valine        leucine
     isobutyraldehyde                             │
          ↓ ADH1-7 / ADH6 / adhA  [NADH or NADPH] │
     ISOBUTANOL                                   │
```

Three things in that diagram are the whole engineering problem, and each is a first-class object
in the schema rather than a remark:

1. **The pathway crosses a membrane.** Upstream is matrix, downstream is cytosol.
2. **The cofactors do not match.** Ilv5 takes NADPH; the alcohol dehydrogenase step typically
   takes NADH ⚠. Pools are compartment-specific, so the imbalance is worse than it looks when
   written as one equation.
3. **The carrier is unidentified.** How 2-ketoisovalerate leaves the matrix in the
   cytosolic-Ehrlich configuration is not settled ⚠. This is modelled as an explicit gap
   (section 5), not as an absent row.

Theoretical mass yield, glucose → isobutanol: **0.411 g/g** (1 glucose → 1 isobutanol + 2 CO₂ +
H₂O; 74.12 / 180.16). Every stored yield is checked against it.

---

## 2. The four strategic configurations

Published work clusters into four families. `pathway_configuration.compartment_strategy` takes
exactly these values, so the literature becomes a four-row comparison.

| strategy | what is done | what it solves | what it costs |
|---|---|---|---|
| **A. Native split** | Leave Ilv enzymes in the matrix, Ehrlich in the cytosol | Nothing — this is the baseline | 2-KIV must cross the membrane by an unidentified route; low flux |
| **B. Cytosolic relocalization** | Truncate the Ilv targeting presequences so Ilv2/Ilv5/Ilv3 stay cytosolic ⚠ | Whole route in one compartment; no 2-KIV export needed | Fe-S maturation of Ilv3 in the cytosol is a known difficulty ⚠; cytosolic NADPH supply; valine pathway perturbed |
| **C. Mitochondrial targeting of the Ehrlich pathway** | Add presequences to a ketoacid decarboxylase and an ADH so they act in the matrix ⚠ | Puts the downstream enzymes where 2-KIV already is; reported to improve isobutanol substantially ⚠ | Matrix NADH/NADPH supply; product must then leave the matrix; matrix volume is small |
| **D. Alternative compartment** | Peroxisomal or other-organelle assembly ⚠ | Isolation from competing cytosolic reactions | Import capacity; cofactor supply; least-explored |

**The most important entry in this table is what it does *not* contain: a row for editing the
mitochondrial genome.** No published isobutanol configuration requires it. Section 4 explains why,
and why the atlas still models it.

---

## 3. The parts catalog

Five step roles. The catalog is what makes role-4 organisms (PLAN.md B.4) worth ingesting at all:
the enzymes come from bacteria even when the host is yeast.

| step | role code | common parts ⚠ | the design variable |
|---|---|---|---|
| Acetolactate synthase | `AHAS` | *S. cerevisiae* Ilv2 (+Ilv6 regulatory subunit); *B. subtilis* AlsS | AlsS is catabolic and not feedback-inhibited by valine, which is why it is preferred in heterologous builds ⚠ |
| Ketol-acid reductoisomerase | `KARI` | *S. cerevisiae* Ilv5; *E. coli* IlvC and its NADH-preferring engineered variants ⚠ | **Cofactor preference.** The single highest-leverage part choice for an anaerobic route |
| Dihydroxyacid dehydratase | `DHAD` | Ilv3; *E. coli* IlvD | [4Fe-4S] cluster: oxygen lability, and cytosolic Fe-S maturation if relocalized ⚠ |
| 2-ketoacid decarboxylase | `KDC` | *L. lactis* KivD; *S. cerevisiae* Aro10, Pdc1/5/6 ⚠ | **Substrate specificity.** Promiscuity across ketoacids sets the isobutanol : isoamyl alcohol ratio |
| Alcohol dehydrogenase | `ADH` | *L. lactis* AdhA; *S. cerevisiae* Adh1–7, Adh6; *E. coli* YqhD ⚠ | Cofactor preference again, and reversibility |

Every part carries `expression_records[]` — one row per host × compartment actually demonstrated,
with whether it expressed, whether activity was measured, and the outcome. "Works in *E. coli*"
and "works in the yeast mitochondrial matrix" are different facts and the catalog refuses to merge
them.

**The cofactor axis is the one to watch.** A route using NADPH-dependent KARI and NADH-dependent
ADH cannot close its redox balance anaerobically without a transhydrogenase-like cycle; swapping
in an NADH-preferring KARI is what made near-theoretical anaerobic isobutanol possible in
*E. coli* ⚠. Whether the equivalent swap carries into yeast, and into which compartment, is a
live question the atlas should be able to state precisely.

---

## 4. Mitochondrial engineering, precisely

The user's brief names mitochondrial genome engineering. Two different things travel under that
name and the distinction changes what is buildable.

### 4.1 Compartment targeting (a nuclear-genome technique)

Change where a **nuclear-encoded** protein ends up, by adding, removing or swapping an N-terminal
mitochondrial targeting sequence. Strategies B and C above are both this. The gene stays in the
nucleus, is transcribed and translated in the cytosol on cytosolic ribosomes, and is imported
post-translationally through the TOM/TIM machinery, with the presequence usually cleaved by the
matrix processing peptidase.

Routine, high-throughput, and what essentially all published mitochondrial isobutanol work
actually is ⚠.

Schema (`modification.type = 'localization_change'`) records: target compartment, the targeting
sequence used and its source, predicted cleavage site, whether an N-terminal fusion remains after
processing, and — mandatory — **`verification_method`**: microscopy, subcellular fractionation,
protease protection, activity in the isolated fraction, or `none_reported`.

That last field earns its place. A localization claim with no localization evidence is common, and
the construct may simply not be imported — in which case every conclusion resting on it is
unsupported. The atlas shows the verification method beside every localization claim rather than
burying it.

Because translation still happens on cytosolic ribosomes, **no recoding is required** for this
technique. This is the point most often confused with 4.2.

### 4.2 Mitochondrial genome engineering (editing mtDNA itself)

Changing the ~86 kb mitochondrial chromosome ⚠, which in *S. cerevisiae* encodes a small set of
respiratory-chain subunits (Cox1, Cox2, Cox3, Cob, Atp6, Atp8, Atp9), the ribosomal protein Var1,
the two rRNAs, the tRNAs and the RNase P RNA ⚠ — and essentially nothing that the isobutanol route
needs.

Available techniques and their honest state ⚠:

| technique | state | note |
|---|---|---|
| Biolistic transformation into a ρ⁰ recipient, then cytoduction | The established route in yeast; practised in a small number of laboratories | Low efficiency; needs a mitochondrial selectable marker, recoded for table 3 |
| mitoTALEN / mitoZFN | Used to shift heteroplasmy by cutting unwanted genomes | Destructive selection, not insertion |
| DdCBE-class base editors | Demonstrated for mitochondrial base editing ⚠ | Point edits, not pathway insertion |
| CRISPR–Cas in the matrix | **Not established** — guide RNA import into mitochondria is the unsolved step ⚠ | This is why mtDNA editing has not followed the nuclear trajectory |

`modification.type = 'mtdna_edit'` carries `technique`, `recipient_state` (ρ⁰ / ρ⁻ / heteroplasmic
ρ⁺), marker, `recoded_for_table_3`, `heteroplasmy_achieved`, and `feasibility_rating` ∈
{`routine`, `specialist`, `frontier`, `not_demonstrated_in_organism`}.

### 4.3 The genetic code constraint

*S. cerevisiae* mitochondria translate by NCBI table 3, not the standard code ⚠:

| codon(s) | standard | yeast mitochondrial |
|---|---|---|
| `UGA` | stop | **tryptophan** |
| `AUA` | isoleucine | **methionine** |
| `CUU CUC CUA CUG` | leucine | **threonine** |
| `CGA` / `CGC` | arginine | absent / unassigned |

The `CUN` block is the dangerous one: a leucine-rich coding sequence moved into mtDNA
mistranslates extensively while still looking like a sensible gene. So:

* A gene placed **into** mtDNA must be recoded for table 3.
* An mtDNA gene expressed **allotopically from the nucleus** must be recoded for table 1.
* A gene merely **targeted** to the matrix (4.1) needs **no** recoding.

Hence `genetic_code_table` is a property of `compartment`, every stored sequence names the
compartment whose code it is written in, and the validator rejects a sequence filed against
`mitochondrial_matrix` that carries an unrecoded `CUN` run. That check is a phase-0 acceptance
criterion precisely because it is cheap to build and expensive to discover later.

### 4.4 What this means for the program

Stated plainly, because it should shape expectations:

> Mitochondrial **compartment engineering** is a central, well-supported and immediately
> actionable route for isobutanol. Mitochondrial **genome engineering** is, for this pathway,
> a frontier technique with no published isobutanol precedent, and the atlas will rank routes
> requiring it accordingly — visible, costed and downweighted, never silently dropped.

If the intent is specifically to put pathway genes into mtDNA, the atlas's most useful service is
to make the cost explicit: the marker system, the ρ⁰ recipient, the recoding, the biolistic
apparatus, the heteroplasmy problem — and the fact that no one has yet done it for this route.
That is a legitimate research programme; it is simply a different one from "build an isobutanol
strain", and conflating them would cost a year.

---

## 5. Gaps as first-class objects

The atlas must store *"this step is required and we do not know how it happens"*.

```
knowledge_gap
  id, kind   transport_carrier_unknown | enzyme_unidentified | mechanism_unknown |
             quantitative_value_missing | never_attempted
  route_step_id, description
  why_it_matters, candidates[] {gene_group, evidence, status}
  publications_asserting_the_gap[]
  status  open | candidate_proposed | resolved
```

Seeded gaps for this programme ⚠:

* the mitochondrial 2-ketoisovalerate carrier;
* isobutanol/isobutyraldehyde export across the plasma membrane;
* cytosolic Fe-S maturation capacity for relocalized Ilv3;
* matrix NADPH supply under production conditions;
* whether an NADH-preferring KARI confers in yeast the benefit it confers in *E. coli*.

A ranked list of gaps, ordered by how many candidate routes they block, is one of the most useful
things the atlas can produce — and it is computable, not editorial.

---

## 6. The chassis question

`chassis_profile` per candidate strain, so "which background" is answerable rather than habitual:

| property | why it matters |
|---|---|
| Existing deletions (*pdc*, *bat*, *leu*, *ald*) | Determines how much of the competition is already removed |
| Pdc status: intact / attenuated / minus (+ C2 requirement, evolved glucose tolerance ⚠) | The single largest determinant of pyruvate availability |
| Transformation efficiency, marker availability, CRISPR toolkit | Build speed |
| Genome and mtDNA availability, ρ⁺/ρ⁰ status | Whether mitochondrial work is possible at all |
| Measured isobutanol tolerance | Caps the useful titer |
| Prior isobutanol record | Comparability to published numbers |
| Industrial robustness | Whether the result transfers beyond the flask |

The expected tension, made explicit by the table: laboratory backgrounds are easy to build in and
have the published comparators; industrial backgrounds tolerate the process. The atlas should not
resolve that for the user — it should show the trade in one view.

---

## 7. What the atlas returns

For *"engineer S. cerevisiae for isobutanol"*, the phase-3 output:

```
ROUTE #n   strategy C · KivD(matrix) + AdhA(matrix) · NADH-KARI · pdc1Δ background
├─ Demonstrated      nearest published configuration, its titer/yield/conditions      [L1/L2]
├─ Balance           carbon ✓  redox ✓ per compartment  ATP ✓                         [computed]
├─ Parts             5 parts, 4 with prior expression in this host/compartment        [L1]
├─ Deletions         PDC1, BAT1 — each with measured consequence and control          [L1/L2]
├─ Bottlenecks       2-KIV supply (7 studies); matrix NADH (3); export (gap)          [L2/L3]
├─ Feasibility       all modifications routine — no mtDNA editing required            [computed]
├─ Ceiling           stoichiometric 0.411 g/g · toxicity-limited ~X g/L               [L2]
├─ Gaps              product export carrier unidentified                              [gap]
└─ Untested          this exact compartment + cofactor combination has no precedent   [Zone I]
```

Every line carries its evidence level and opens its chain. The last line is the one that makes it
a design tool rather than a review: it is computed as the complement of the evidence, and it is
where the next experiment lives.
