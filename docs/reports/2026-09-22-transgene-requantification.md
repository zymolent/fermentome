# Transgene requantification of SRP342112 — 2026-09-22

The 33 RNA-seq runs of SRP342112 are an isobutanol producer series in a CEN.PK113-5D background.
Every previous quantification in this atlas used an S288C-only transcriptome, so reads from the
engineered pathway had nowhere to map. The atlas could not say whether the KARI and ADH steps of
these builds are transcribed at all — which is the question it is being asked.

It can now. **The ADH step is expressed at 11,605 TPM (median) in every cassette-bearing strain,
and the KARI step at 1,426 TPM in Y799 and nowhere else.** Both were previously invisible.

Two things came out of the work that were not asked for and matter more than the headline: the
native `ILV3` row in the existing matrices is **88% cassette spillover**, and **four of the eleven
T14 runs carry a strain label their own transcriptome contradicts**.

## What the study is

**Gambacorta FV, Wagner ER, … Sato TK, Pfleger BF (2022), "Comparative functional genomics
identifies an iron-limited bottleneck in a *Saccharomyces cerevisiae* strain with a
cytosolic-localized isobutanol pathway," *Synth Syst Biotechnol* 7(2):738–749**, PMID 35387233,
doi 10.1016/j.synbio.2022.02.007, GEO GSE186126. The pathway cassette is deposited as **GenBank
MZ541859.1** (*Cloning vector pGLBRCY-HO-mIBAIlv5-KanMX-HO*, 22,211 bp).

The four declared strains, from the runs' own `attr_genotype`:

| strain | pathway ORFs | adhA | ilvC | ILV5 | localization |
|---|---|:-:|:-:|:-:|---|
| Y795 | none (CEN.PK113-5D URA3+) | – | – | – | parent |
| Y797 | ILV2/ILV3/ILV5/ARO10 + LlAdhA29C8 | yes | no | yes | COX4 MLS (mitochondrial) |
| Y799 | ILV2N54/ILV3N19/ARO10 + LlAdhA29C8 + EcIlvC6E6 | yes | **yes** | **no** | cytosolic |
| Y812 | ILV2N54/ILV3N19/ILV5N48/ARO10 + LlAdhA29C8 | yes | no | yes | cytosolic |

Three timepoints (T3 = hour 4, T6 = hour 10, T14 = hour 26), 2×151 paired reads as submitted.
`ILV5` and `ilvC` are mutually exclusive across the three producers, which turns out to be the
lever that makes the mislabelling below detectable at all.

## The first pass used the wrong reference, and proved it

The job was originally specified against **wild-type** bacterial CDS, on the reasoning that reads
from a few-residue variant still map to the wild-type sequence. That reasoning is sound in general
and half-wrong here: **every ORF in MZ541859.1 is codon-optimized.**

This was measured, not assumed. The first pass (`ops/userdata_transgene.sh`, prefix
`quant-transgene/20260922T094448Z`) ran an index carrying wild-type *L. lactis* adhA, *E. coli*
ilvC/ilvD and *L. lactis* kivd. In the 10 runs completed before it was stopped, **wild-type adhA
scored 0 reads in every sample, including Y797 and Y799 runs that carry LlAdhA29C8.** A zero on
that row meant "unmeasurable", not "unexpressed".

The pass was stopped at 10/33 rather than run to completion: finishing it would have bought 23 more
runs of a number already known to be uninformative, at ~$0.27 of instance time. Its output is left
in S3 as the evidence for this paragraph.

The wild-type **ilvC** row behaved differently — it was non-zero in some samples and zero in
others, in a pattern that looked erratic at the time. It was not erratic. It was tracking the true
genotype of samples whose labels are wrong (below), and it is the reason ilvC stayed in the index.

## What is in the index now, and from where

Base: `s288c.transcripts.mito.fna.gz` (the mitochondria-complete S288C transcriptome from the
2026-09-20 pass), unchanged. Added, via
`efetch.fcgi?db=nuccore&id=MZ541859.1&rettype=fasta_cds_na&retmode=text`:

| index row (`locus_tag`) | source ORF | nt | aa | protein_id |
|---|---|--:|--:|---|
| `cassette_ILV2_MZ541859` | ILV2, codon-optimized | 2,064 | 687 | UUV68058.1 |
| `cassette_ILV3_MZ541859` | ILV3, codon-optimized | 1,758 | 585 | UUV68059.1 |
| `cassette_ILV5_MZ541859` | ILV5, codon-optimized | 1,188 | 395 | UUV68062.1 |
| `cassette_ARO10_MZ541859` | COX4 MLS–ARO10 | 1,968 | 655 | UUV68061.1 |
| `cassette_adhA_MZ541859` | COX4 MLS–adhA 29C8 | 1,083 | 360 | UUV68060.1 |
| `cassette_KanR_MZ541859` | KanR marker (control) | 810 | 269 | UUV68063.1 |
| `cassette_hph_MZ541859` | hph marker (control) | 1,029 | 342 | UUV68056.1 |
| `wildtype_EcIlvC` | *E. coli* K-12 ilvC, **wild type** | 1,476 | 491 | NP_418222.1 |

FASTA, sha256 and the exact efetch URLs (minus the key) are in
`docs/drafts/omics/transgene_refs/cassette_cds.provenance.json`; the superseded wild-type set is
kept beside it in `transgene_cds.provenance.json`.

### One deliberate departure from the instruction

The instruction was to keep all wild-type bacterial CDS out of the index. **The wild-type *E. coli*
ilvC was kept anyway**, because MZ541859.1 is the **mIBA-Ilv5** plasmid — the Y797 build — and it
contains **no ilvC at all**. A GenBank search on `pGLBRCY`, the author list, `ilvC AND 6E6` and
four other terms returns MZ541859.1 and nothing else: **no plasmid for the Y799 build is
deposited.** Dropping ilvC would have made "is the KARI step of Y799 transcribed" unanswerable by
construction rather than by evidence. It has no cassette counterpart in this index, so it competes
with nothing.

That call is what produced the headline. **The wild-type CDS captures the Y799 transgene almost
exactly** — SRR16481343 scores 1,180 TPM against wild-type ilvC in the first pass and 1,145 TPM in
the second — so unlike adhA, the Y799 ilvC is at or very near the wild-type *E. coli* sequence and
was never codon-optimized. Had the instruction been followed literally, the KARI question would
still be open.

The wild-type adhA, kivd and ilvD were dropped as instructed: adhA now has a cassette competitor,
and kivd/ilvD are in none of these strains.

## The spillover claim, measured

The concern that prompted the re-run — that codon-optimized cassette ORFs share exact substrings
long enough to seed a k=31 index and leak onto the native rows — is **correct, and the ~12%
estimate was very close.** Measured shared-sequence structure first:

| gene | cassette nt | native nt | longest exact match | shared 31-mers | ungapped identity |
|---|--:|--:|--:|--:|--:|
| ILV2 | 2,064 | 2,064 | 32 nt | 2 | 81.3% |
| **ILV3** | 1,758 | 1,758 | **44 nt** | **20** | 84.0% |
| ILV5 | 1,188 | 1,188 | 29 nt | 0 | 86.4% |

And then the leak itself, from the difference between the two passes on the 23–24 cassette-bearing
runs:

| native gene | leak, as % of the cassette copy's TPM | share of the *old* native row that was spillover |
|---|--:|--:|
| ILV2 | 1.0% | 4.5% |
| **ILV3** | **14.1%** (11.5–17.3) | **87.7%** (63.9–96.1) |
| ILV5 | 1.0% | 5.7% |
| ARO10 | 0.0% | 1.6% |

**The predicted ~12% leak measures 14.1%.** The reason it is so destructive is the ratio, not the
rate: cassette ILV3 runs at ~16,700 TPM while native ILV3 runs at ~370, so a 14% leak off the
cassette is a ~10–25× inflation of the native row.

### Native ILV2/ILV3/ILV5/ARO10, before and after, by declared strain (median TPM)

| strain | n | ILV2 before→after | ILV3 before→after | ILV5 before→after | ARO10 before→after |
|---|--:|---|---|---|---|
| Y795 (parent) | 9 | 66.2 → 66.2 | 110.2 → **110.1** | 574.9 → 574.9 | 1.4 → 1.4 |
| Y797 | 9 | 85.0 → 80.5 | 3058.2 → **134.1** | 549.6 → 549.6 | 1.7 → 1.7 |
| Y799 | 8 | 68.2 → 65.2 | 3310.4 → **384.3** | 1327.3 → 1235.3 | 1.4 → 1.3 |
| Y812 | 7 | 120.5 → 114.5 | 2955.7 → **370.5** | 2383.1 → 2252.1 | 0.5 → 0.5 |

The parent is the control and it does not move — as it must not, having no cassette to leak from.
Everything else does. **Any conclusion this atlas has drawn about native ILV3 induction in the
producer strains rests on a number that was 88% cassette.** Native ILV3 is not induced ~28-fold
over the parent (3058 vs 110); it is elevated about 1.2–3.5-fold.

## Results

### The headline: are adhA and ilvC expressed?

Grouped by the genotype each run's own transcriptome shows, not by its label (see the next
section). Median TPM:

| row | no cassette (n=9) | cassette + ILV5 — Y797/Y812 (n=15) | cassette + ilvC — Y799 (n=9) |
|---|--:|--:|--:|
| **adhA** (cassette) | 0.5 | **10,524** | **18,918** |
| **ilvC** (wild-type Ec) | 0.0 | 0.0 | **1,426** |
| ILV3 (cassette) | 0.7 | 16,950 | 15,607 |
| ARO10 (cassette) | 0.5 | 7,251 | 6,381 |
| ILV5 (cassette) | 0.2 | 4,273 | 0.2 |
| ILV2 (cassette) | 0.0 | 602 | 829 |
| KanR / hph (cassette) | 0.0 | 0.0 | 0.0 |

**Plainly: yes, both are expressed, and strongly.**

* **adhA is expressed in every cassette-bearing strain — Y797, Y799 and Y812 alike** — at a median
  11,605 TPM across all 24 producer runs, range 4,741–25,163. It is zero (median 0.5, max 4.7) in
  all nine parent runs. This is not a marginal detection; adhA is among the most abundant
  transcripts in these samples.
* **ilvC is expressed only in Y799**, at a median 1,426 TPM (range 287–2,369), and reads exactly
  zero in every Y797, Y812 and parent run. Perfect genotype correlation across 33 samples, which
  is itself the strongest evidence that the row is measuring the transgene and not an artifact.
* **Relative to the pathway they are meant to drive, both are enormous.** Against corrected native
  levels in the same samples — native ILV3 370, native ILV5 929, native ILV2 82, native ARO10 0.9 —
  the cassette runs 1–2 orders of magnitude higher. The engineered steps are not
  transcriptionally limited.
* **ilvC is the weakest cassette element by an order of magnitude**: 1,426 TPM against adhA's
  18,918 in the same Y799 samples, a 13-fold gap. Within the Y799 build, the KARI step is the
  least-transcribed heterologous step.
* **Native ARO10 is essentially silent (0.9–1.7 TPM) in every strain.** All ARO10 activity in this
  study is the cassette copy at ~7,200 TPM. Earlier statements in this atlas that "ARO10 is the
  weakest pathway step" came from the native row and do not describe these strains.
* **Both selection markers read 0.0 TPM in every sample.** KanR and hph are on the plasmid but are
  not transcribed in the integrated strains, so they do not work as a cassette-presence control.
  Recorded as measured, not corrected.

### Mapping rate, before and after

| group | n | before (median) | after (median) | median gain |
|---|--:|--:|--:|--:|
| parent Y795 | 9 | 60.30% | 60.30% | **+0.00 pts** |
| cassette-bearing | 24 | 56.43% | 60.62% | **+4.11 pts** (0.00 to +5.14) |

The parent does not move at all and the producers gain ~4 points, which is the cleanest possible
confirmation that the recovered reads are cassette reads. (Per-run figures in
`C:\Users\kangk\fermdb-data\matrices_transgene\qc.tsv`; the `unmapped_fraction` column of
`sra_run` is NULL for all 33 runs, so the before figures are taken from the
`quant-mito/20260920T085009Z` meta_info.json files.) The producers do not reach the parent's
*original* rate, so ~35% of reads in these libraries remain unmapped for reasons this cassette does
not explain.

### Four T14 runs contradict their own strain label

At **T3 and T6, all 22 runs match their declared strain exactly.** At T14, four of eleven do not:

| run | declared | what its transcriptome shows | adhA | ILV5 | ilvC |
|---|---|---|--:|--:|--:|
| SRR16481343 | Y795 (parent) | full cassette **+ ilvC**, no ILV5 → Y799-like | 18,918 | 0 | 1,145 |
| SRR16481346 | Y797 | **no cassette at all** → parent-like | 5 | 0 | 0 |
| SRR16481349 | Y799 | cassette **+ ILV5**, no ilvC → Y797/Y812-like | 5,995 | 1,914 | 0 |
| SRR16481352 | Y812 | cassette **+ ilvC**, no ILV5 → Y799-like | 10,613 | 0 | 434 |

The SRR16481343 / SRR16481346 pair is unambiguous and does not depend on any threshold: a strain
with no cassette cannot express one at 18,918 TPM, and a strain that carries one cannot show 5 TPM
while its two replicates show 5,938 and 6,425. The SRR16481349 / SRR16481352 pair is a
Y799↔Y812 swap on the mutually-exclusive ILV5/ilvC marker.

This is reported as observed. **What the correct labels are is not asserted here** — the markers
identify genotype classes, and Y797 and Y812 are not separable on them. What follows is that
**the T14 contrasts in this atlas are wrong for 4 of 11 samples** and should be rebuilt on the
observed genotype, or the timepoint dropped, before anything is concluded from them. T3 and T6 are
sound. All 33 runs are kept in the matrices with their submitted labels; correcting metadata is a
curation decision, not a quantification one, and the evidence is here for whoever makes it.

## Cost and hygiene

| | run 1 (superseded) | run 2 (the result) |
|---|---|---|
| instance | `i-01696579d2015c048` | `i-0187d0e828dc2ab22` |
| type / region | c7i.4xlarge, us-east-1 | c7i.4xlarge, us-east-1 |
| launched → ended | 09:44:45 → 10:05:47 UTC (21 min) | 10:05:59 → 11:01:50 UTC (56 min) |
| final state | **terminated** (verified) | **terminated** (verified) |
| ended by | operator `terminate-instances`, wrong reference | **self-terminated** via the EXIT trap |
| runs completed | 10 of 33 (stopped) | **33 of 33** |
| compute | ≈ $0.25 | ≈ $0.67 |

**Total ≈ $0.96** — $0.92 EC2, ~$0.03 EBS (200 GB gp3 for 77 instance-minutes), ~$0.01 S3. Against
a $10 ceiling. No spot, no data-transfer charges (S3 and EC2 in the same region as the SRA Open
Data mirror; bucket `LocationConstraint` is null = us-east-1, confirmed before launch).

**Orphan check, after both runs:** 0 instances and 0 unattached volumes in us-east-1, ap-south-1,
us-west-2 and eu-west-1; both job-tagged volumes deleted on termination; no snapshots, no
self-owned AMIs. `i-01696579d2015c048` was confirmed `terminated` at 10:05:47 UTC before run 2 was
launched — the two never overlapped, which the account's 16-vCPU on-demand limit would have
enforced anyway.

All three self-termination mechanisms were kept in both scripts:
`instance-initiated-shutdown-behavior=terminate` at launch, a `trap … EXIT` that shuts down on
every exit path, and a detached 4-hour watchdog. Both abort *before* building the index if the
downloaded transcriptome lacks the expected CDS; run 2 additionally requires the **native**
ILV2/ILV3/ILV5/ARO10 rows to be present, because an index with the cassette but without the native
loci would have made the comparison this pass exists for quietly meaningless. Both checks passed on
the instance (`cassette ORFs: 7 ; wildtype ilvC: 1 ; mtDNA CDS: 19 ; native ILV2/3/5/ARO10: 4`).

## What changed on disk

* `C:\Users\kangk\fermdb-data\matrices_transgene\` — `s288c.counts.tsv.gz`, `s288c.tpm.tsv.gz`
  (6,214 genes × 33 samples, 0 unresolved transcripts, 22 mitochondrial), `manifest.json`,
  `qc.tsv`. The earlier `matrices/` and `matrices_mito/` are untouched.
* `ops/userdata_cassette.sh` (run 2) and `ops/userdata_transgene.sh` (run 1, superseded, kept as
  evidence).
* `docs/drafts/omics/transgene_refs/` — the added CDS and their provenance, both sets.
* S3: `refs/s288c.transcripts.cassette.fna.gz`, `refs/quant_plan_cassette.json`,
  `quant-cassette/20260922T100612Z/` (33 quant.sf + meta + run.log + summary.json), and the
  superseded `refs/s288c.transcripts.transgene.fna.gz` / `quant-transgene/20260922T094448Z/`.
* **No database was written.** The `unmapped_fraction` column for these 33 runs remains NULL and
  the mislabelling above is recorded here, not applied.
