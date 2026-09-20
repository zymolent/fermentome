# DUET expression baseline — 2026-09-20

The first read-out the atlas makes from its own data: 36 resolved DUET genes profiled across
**99 *S. cerevisiae* RNA-Seq runs** quantified against the R64 transcriptome
(`s288c.tpm.tsv.gz`, 6,187 genes × 99 samples). Zone H throughout — rebuildable by re-running
`fermdb.omics.baseline` — except the interpretation, which is Zone I and is prose, not rows.

No differential expression, no fold changes, no sample grouping. PLAN.md F.3 requires an approved
`condition_context` for any contrast and none is curated; the 99 runs come from fifteen unrelated
studies. Grouping them by anything available would invent exactly the metadata F.3 says this
corpus lacks, and would look just as rigorous while meaning nothing.

## The finding that changes what can be claimed

**Mitochondrial gene expression was never measured.** The R64 `rna_from_genomic` transcriptome
that the salmon index was built from contains **no mtDNA protein-coding genes at all**:

> COX1, COX2, COX3, COB, ATP6, ATP8, ATP9, VAR1 — all absent.

Its 27 mitochondrial features are 24 tRNAs, 2 rRNAs (`Q0020` 15S, `Q0158` 21S) and one ncRNA
(`Q0285` RPM1). Those three non-tRNA rows are the only `Q`-prefixed entries in the matrix, and a
first pass at this analysis was about to report them as "mitochondrial genes are lowly expressed"
— median 7.3, 5.0 and 0.5 TPM. They are ribosomal and non-coding RNA. They say nothing whatever
about whether the organelle is transcriptionally equipped for the load DUET would place on it.

Consequences, stated plainly:

* **Strategy E (mtDNA-encoded genes) has no transcriptomic evidence base here.** Not weak
  evidence — none. Any ranking that scores E against C on expression grounds would be scoring it
  against a measurement that does not exist.
* Reads from mitochondrial mRNAs had nowhere to map and sit in the unmapped fraction, which is
  part of why the median mapping rate is 78.6% rather than higher.
* The fix is a reference-construction change, not more sequencing: build the yeast index from a
  transcriptome that includes the mitochondrial CDS, or add those eight CDS explicitly, then
  requantify from the S3 raw objects.

This is a reference gap, not biology. It cost nothing to find and would have been very expensive
to discover after a route ranking had been built on it.

## What the nuclear genes say

All 36 resolved genes are nuclear-encoded and all 36 are present in the matrix. None is absent
from every sample.


**Pathway**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| ILV5 | `YLR355C` | 173.6 | 39.7–3,655 | 99/99 |
| ILV6 | `YCL009C` | 137.3 | 7.4–1,698 | 99/99 |
| LEU4 | `YNL104C` | 130.8 | 29.5–578 | 99/99 |
| BAT2 | `YJR148W` | 117.2 | 15.1–626 | 99/99 |
| ILV3 | `YJR016C` | 107.0 | 26.1–4,107 | 99/99 |
| ILV2 | `YMR108W` | 62.2 | 6.1–326 | 99/99 |
| BAT1 | `YHR208W` | 56.2 | 16.5–1,037 | 99/99 |
| LEU9 | `YOR108W` | 16.5 | 2.9–159 | 99/99 |
| ARO10 | `YDR380W` | 9.2 | 0.0–118 | 78/99 |

**Redox shuttle**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| ADH3 | `YMR083W` | 232.0 | 44.9–557 | 99/99 |
| ADH2 | `YMR303C` | 102.9 | 1.3–676 | 99/99 |
| POS5 | `YPL188W` | 19.4 | 6.1–56 | 99/99 |

**Competing / by-product**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| PDC1 | `YLR044C` | 3,027.8 | 162.8–11,249 | 99/99 |
| ALD6 | `YPL061W` | 390.2 | 8.8–772 | 99/99 |
| GPD1 | `YDL022W` | 237.9 | 5.7–897 | 99/99 |
| BDH1 | `YAL060W` | 105.5 | 4.7–431 | 99/99 |
| ATF1 | `YOR377W` | 39.2 | 0.0–155 | 97/99 |
| BDH2 | `YAL061W` | 24.3 | 0.0–290 | 87/99 |
| PDC5 | `YLR134W` | 14.5 | 1.1–5,635 | 99/99 |
| ECM31 | `YBR176W` | 11.4 | 1.7–30 | 99/99 |

**Pentose / PPP**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| TAL1 | `YLR354C` | 268.2 | 37.4–1,778 | 99/99 |
| TKL1 | `YPR074C` | 132.2 | 43.1–1,196 | 99/99 |
| RPE1 | `YJL121C` | 83.4 | 10.1–649 | 99/99 |
| XKS1 | `YGR194C` | 27.0 | 0.8–66 | 98/99 |
| RKI1 | `YOR095C` | 19.2 | 1.6–173 | 99/99 |

**Efflux / tolerance**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| PMA1 | `YGL008C` | 334.9 | 30.4–3,912 | 99/99 |
| PDR5 | `YOR153W` | 44.5 | 6.2–789 | 99/99 |
| PTK2 | `YJR059W` | 38.0 | 1.1–120 | 99/99 |
| SNQ2 | `YDR011W` | 21.8 | 2.5–133 | 99/99 |
| YOR1 | `YGR281W` | 14.9 | 1.0–113 | 99/99 |

**Fe-S machinery**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| SOD2 | `YHR008C` | 372.9 | 1.8–993 | 99/99 |
| ISU1 | `YPL135W` | 369.2 | 8.9–1,501 | 99/99 |
| YFH1 | `YDL120W` | 52.8 | 6.6–245 | 99/99 |
| NFS1 | `YCL017C` | 29.5 | 3.2–66 | 99/99 |

**Global regulation**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| SPT15 | `YER148W` | 80.6 | 6.6–223 | 99/99 |

**unknown**

| gene | systematic | median TPM | range | detected |
|---|---|--:|--:|--:|
| PDC6 | `YGR087C` | 6.6 | 0.0–740 | 89/99 |

## Three things worth acting on

**ARO10 is the weakest pathway step by an order of magnitude.** Median 9.2 TPM, and undetected in
21 of 99 samples — the only pathway gene that is not universally detected. It catalyses the
Ehrlich decarboxylation (2-ketoisovalerate → isobutyraldehyde), so the committed step toward the
product is the one the cell natively expresses least. Every other pathway enzyme is 6–19× higher.

**The competing drain outweighs the pathway by two orders of magnitude.** PDC1 sits at a median
3,028 TPM against ARO10's 9.2 — a 330-fold difference at the branch point where pyruvate is
either decarboxylated toward ethanol or retained for valine biosynthesis. ALD6 (390) and GPD1
(238) add further pull. This is a quantitative statement of the problem the DUET design exists to
address, measured rather than assumed.

**POS5 is low for its load-bearing role.** Median 19.4 TPM — the second-lowest of the redox set,
against ADH3 at 232. POS5 is the mitochondrial NADH kinase that supplies matrix NADPH, which is
what Ilv5 consumes; in the DUET architecture it is the coupling between ethanol-derived matrix
NADH and the pathway's reductive step. ILV5 itself is at 174 TPM, roughly 9× its NADPH supplier.

Read together: the native cell expresses the *upstream* pathway adequately, supplies its
cofactors thinly, and routes the great bulk of carbon to ethanol. That ordering — drain first,
cofactor second, pathway last — is what a route ranking should weight.

## Caveats a curator should keep

* **TPM across fifteen studies is not a clean comparison.** Library chemistry differs (91 of 102
  yeast runs are `cDNA` selection, 8 are `RANDOM`), and TPM is within-sample normalised. Medians
  across a heterogeneous corpus indicate typical abundance; they do not support a between-study
  claim.
* **The spreads are large and are not noise to be averaged away.** ILV3 ranges 26 to 4,107 TPM
  and PDC5 1.1 to 5,635. Those ranges are almost certainly condition effects — which is precisely
  the signal a curated `condition_context` would let us read, and the argument for curating one.
* Detection is TPM ≥ 1.0, a stated threshold, not a measured boundary.

## What this unblocks, and what it does not

Route enumeration (G.7) can now weight steps by native expression, and can carry ARO10's low
expression and PDC1's dominance as scored terms rather than assumed ones.

It cannot yet rank strategy C against strategy E on expression evidence. That needs the
mitochondrial CDS added to the index and the S3 raw objects requantified — the one piece of
compute work this analysis shows is worth doing.
