# DUET — the strain this atlas exists to design

Imported 2026-09-20 from `D:\Agentic\isobutanol proposal` (DUET concept note and DUET form
answers). **This is the project's destination.** Everything in the atlas should be read as serving
it, and where the atlas's scope disagrees with it, the atlas is wrong.

Source documents are the owner's own prior work, not third-party claims. Gene symbols below are
taken verbatim from the concept note; the biology attributed to them is marked ⚠ where it is my
reading rather than their statement.

---

## 1. The concept in one paragraph

An engineered **industrial polyploid *S. cerevisiae*** for an existing Indian 2G ethanol plant.
The C6 stream keeps making ethanol on the untouched existing train; the stranded **C5 pentose
stream** — roughly a third of the fermentable sugar, currently burned or sent to biomethanation —
is fermented to **isobutanol** in a bolt-on fermenter. Recovery uses waste CO₂ from the adjacent
ethanol fermenter as strip gas, and isobutanol's heterogeneous azeotrope with water means the
condensate self-separates in a decanter. TRL 3 → TRL 5 at 5,000 L.

## 2. The four architectural claims

| claim | what it means |
|---|---|
| **Ethanol as redox carrier** | Incumbents delete pyruvate decarboxylase. DUET **retains and strengthens** the ethanol–acetaldehyde shuttle, because ethanol diffuses into the matrix and is oxidised there by **Adh3**, delivering reducing power. Co-production is a design requirement, not a compromise |
| **Substrate partitioning** | C6 → ethanol, C5 → isobutanol, so the two products stop competing for pyruvate. Glucose-repressed promoters make the switch automatic — "carbon-programmed switching", no inducer |
| **Mitochondrial, not cytosolic** | The whole pathway runs in the matrix where 2-KIV is already made and **Ilv3 already folds**, so the cytosolic Fe-S problem never arises — and it sits outside the incumbent patent space |
| **Fe-S protection, dual-purpose** | Isobutanol toxicity destroys Fe-S clusters and the rate-limiting enzyme is one. One intervention serves both tolerance and flux |

## 3. Gene set named in the concept note

| role | genes |
|---|---|
| Pathway | `ILV2` `ILV6` `ILV5` `ILV3` `ARO10` `BAT1` `BAT2` `LEU4` `LEU9` |
| **Redox shuttle** | `ADH3` (mitochondrial ADH) · `ADH2` · **`POS5`** (mitochondrial NADH kinase) |
| Pentose / PPP | `XKS1` `TAL1` `TKL1` `RKI1` `RPE1` |
| Competing / by-product | `PDC1` `PDC5` `ALD6` `GPD1` `BDH1` `BDH2` `ATF1` **`ECM31`** |
| Fe-S machinery | `NFS1` `ISU1` `YFH1` · `SOD2` |
| Efflux / tolerance | `PDR5` `SNQ2` `YOR1` `PTK2` `PMA1` |
| Global regulation | `SPT15` (gTME) |

## 4. Where DUET sits in the atlas's own taxonomy

**DUET is strategy C** — mitochondrial targeting of the Ehrlich pathway by nuclear-encoded,
presequence-targeted enzymes (`ISOBUTANOL_PROGRAM.md` §2). That is exactly the strategy
`MITOCHONDRIAL_PROGRAM.md` §1 recommends running **first**, and for the same stated reason: it
avoids the cytosolic Fe-S maturation problem and has precedent.

So the atlas's standing advice and the proposal already agree. **mtDNA genome engineering
(strategy E) is a later, additional strategy** — the "further strategy and modifications" beyond
DUET — and the escalation condition remains the one already written down: attempt E when C is
demonstrated to be **import-limited**.

## 5. Four places the atlas is currently scoped WRONG

Each of these is a scoping error relative to the destination, not a difference of opinion.

### 5.1 Ethanol is scoped as the enemy. DUET needs it as the mechanism. *(most serious)*

`PLAN.md` B.3.1 makes criterion **E1 "the competing sink"** — *PDC* deletions, `pdc1Δ2Δ3Δ`
chassis, the C2 auxotrophy — and calls a Pdc-minus background "the likely starting chassis".

**DUET does the opposite and says so explicitly.** Deleting PDC cripples the yeast and removes
the redox carrier the matrix pathway depends on.

**Required change: a fifth admission criterion, E5 — ethanol as mitochondrial redox shuttle.**
Its literature is distinct and currently unscoped: `ADH3` and mitochondrial alcohol dehydrogenase,
the ethanol–acetaldehyde shuttle as a route for cytosol→matrix reducing equivalents, matrix NADH
pools, and `POS5`. E1 stays — knowing what PDC deletion costs is still needed — but it is no
longer the primary framing, and the chassis is Pdc-**positive**.

### 5.2 Pentose utilisation is explicitly excluded. DUET is built on it.

B.3.5 lists "pentose utilisation engineering" among the exclusions. DUET's entire substrate
partition is C5 → isobutanol, and `XKS1 TAL1 TKL1 RKI1 RPE1` are core genes.

**Required change:** remove the exclusion; add xylose/arabinose utilisation, the non-oxidative
PPP, and **glucose repression / carbon-source switching** as first-class. The `condition_context`
model must handle mixed and sequential carbon sources, not one carbon source per context.

### 5.3 The strain recommendation is wrong.

I recommended CEN.PK113-7D two messages ago. DUET uses **an industrial polyploid strain the owner
already holds, at ~120 g/L ethanol**, with marker-free multiplex editing.

**Required change:** `chassis_profile` must model **ploidy**, marker-free editing, and industrial
robustness. CEN.PK becomes a *comparator* for quantitative physiology, not the chassis. The
mitochondrial-genetics background remains relevant only for strategy E later.

### 5.4 Downstream is excluded. DUET's recovery is part of the novelty.

`PLAN.md` A.2 excludes downstream processing and TEA. DUET's CO₂-stripping / self-decanting
recovery is a patent family in its own right — and, more importantly for the atlas, **in-situ
product removal changes what a titer means**. A 2 g/L titer under continuous stripping is not the
same measurement as 2 g/L in a sealed flask.

**Required change (minimum):** `in_situ_product_removal` as a `condition_context` facet, so
ISPR and non-ISPR titers are never silently compared. Full downstream modelling stays out.

## 6. Two additions

* **Patent / FTO landscape.** Never scoped. Q8 commits to four patent families and an FTO opinion
  against the **Gevo, Butamax and DuPont** estates within six months. The atlas should hold a
  patent layer alongside publications — at minimum, claims relevant to mitochondrial isobutanol
  pathways, so "does this route sit inside someone's claim space" is answerable.
* **`ECM31` — a 2-KIV drain I had missed.** My pathway sketch had the valine (`BAT1/BAT2`) and
  leucine (`LEU4/LEU9`) branches but not ketopantoate hydroxymethyltransferase, which pulls
  2-ketoisovalerate into pantothenate biosynthesis ⚠. It belongs in the competing-reaction set.

## 7. The analytical observation worth acting on

The redox architecture closes, and `POS5` is what closes it:

```
ethanol (cytosol) --diffuses--> matrix
   --Adh3--> acetaldehyde + matrix NADH
        |
        +--> final ADH step of the Ehrlich pathway          [needs NADH]  ✔
        |
        +--Pos5 (mitochondrial NADH kinase)--> matrix NADPH
                 --> Ilv5 / KARI                             [needs NADPH] ✔
```

Ilv5 needs NADPH and the Ehrlich ADH step needs NADH; ethanol oxidation by Adh3 supplies NADH
directly, and `POS5` is the only named route from matrix NADH to matrix NADPH ⚠. That makes the
architecture coherent — and it makes **`POS5` a single point of failure**. If matrix NADH-kinase
flux is insufficient, the pathway stalls at Ilv5 no matter how well everything else works.

**Therefore: `POS5` capacity is the atlas's highest-priority bottleneck hypothesis**, and the
alternative that de-risks it — an **NADH-preferring KARI variant**, which removes the NADPH
requirement altogether — is the highest-priority parts-catalog question. Both should be seeded as
`knowledge_gap` rows before curation starts, so the literature search is actively looking for
them rather than stumbling on them.

## 8. What this changes about priority

The curated paper set already in `D:\Agentic\isobutanol proposal\papers` — Atsumi 2008,
Avalos 2013, Baez 2011, Chen 2016, Sherkhanov 2020, Nawab 2024 and two supplementaries — is a
ready-made phase-1 seed. Those eight go in first, with full extraction, because they are already
judged relevant by the person the atlas is for.
