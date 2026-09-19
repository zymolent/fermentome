# Data volume — dry assessment

Scope: phases 0–3 **plus the isobutanol omics layer**, which is now in scope.
All corpus sizes are **measured against PubMed, SRA and GEO on 2026-09-19**. Anything derived from
them is arithmetic and labelled as such. ⚠ marks a figure from background knowledge.

---

## 0. Headline

| | |
|---|---|
| **Entire isobutanol SRA corpus** | **~48–51 GB** — two runinfo fetches of the same query disagree (120 runs / 51,076 MB vs ~148 runs / ~48.4 GB). **Both are recorded, neither is discarded** — see §2 |
| Retained after processing | **~4–6 GB** total project, including PDFs and database |
| Transient during processing | ~100–140 GB, streamed and deleted |
| Compute | **~100–150 core-hours** (corrected — see §5) |
| AWS bill for the whole omics campaign | **~$5–20**, and nearly invariant to instance size (§6) |
| Binding constraint | **still curation hours (~450 h), not bytes** |

Adding omics costs roughly **+2 GB retained and one day of compute**. It does not change the
shape of the project. What it does change is expectations about what the omics can prove —
see §4, which is the part worth reading.

---

## 1. Literature corpus — measured (PubMed)

| query | hits |
|---|---|
| `isobutanol` (all) | **1,027** |
| `isobutanol AND (production OR biosynthesis OR fermentation)` | **768** |
| `isobutanol AND (Saccharomyces OR yeast)` | **251** |
| `isobutanol AND (mitochondri* OR matrix OR compartment)` | **33** |
| mtDNA transformation / genome engineering / editing + yeast | **823** |
| mtDNA methods (biolistic, mito-base-editing, allotopic) + yeast | **919** |
| `ethanol AND mitochondri* AND yeast` | **642** |
| `ethanol AND Saccharomyces cerevisiae AND (production OR fermentation OR tolerance)` | **6,072** |

*(Three rows added 2026-09-20. They were measured on 2026-09-19/20 alongside the others but were
not carried into this table, because at the time neither the mitochondrial methods layer nor
criterion E5 had a scoping decision that needed sizing. Both now do.)*

Two of the new rows size decisions that were previously guesses:

* **33 records for isobutanol × mitochondria.** The compartment-targeted route — DUET's strategy C,
  and the strategy `ISOBUTANOL_PROGRAM.md` §4 recommends running first — has a literature of a few
  dozen papers. That is small enough to read **completely and by hand**, which is the right way to
  treat the core of the program, and it is a useful corrective to any expectation that automated
  screening is what makes strategy C tractable.
* **642 records for ethanol × mitochondria × yeast.** This is the outer bound on criterion **E5**
  (PLAN.md B.3.5, ethanol as mitochondrial redox shuttle), against 6,072 for the general ethanol
  query. E5 is therefore **~10% of the ethanol literature**, not a marginal addition — and it still
  sits under the existing ~150-publication ethanol cap only because E5 admits the shuttle
  mechanism, not mitochondrial biology in general. That narrowing is what the criterion's
  exclusions in B.3.5 do, and 642 is the number that shows why they are load-bearing.

The literature asymmetry is ~6×, on a deliberately narrowed ethanol query. The isobutanol
literature at 1,027 records is small enough to screen completely, which is the premise the
primary/reference split rests on.

---

## 2. Omics corpus — measured (SRA and GEO)

| query | records |
|---|---|
| SRA `isobutanol` | **147** |
| SRA `isobutanol AND Saccharomyces` | **80** |
| SRA `isobutanol AND "Escherichia coli"` | **40** |
| GEO series (GSE) `isobutanol` | **13** |
| SRA `butanol OR "branched-chain alcohol" OR "2-ketoisovalerate"` | **960** (mostly *n*-butanol / ABE, adjacent tier) |
| SRA `ethanol AND "Saccharomyces cerevisiae"[Organism]` | **13,117** |
| SRA `"Saccharomyces cerevisiae"[Organism] AND transcriptomic[Source]` | **50,626** |

### The actual bytes, from SRA runinfo

Fetched for the full `isobutanol` result set:

| | |
|---|---|
| Runs with runinfo | **120** |
| **Total size** | **51,076 MB ≈ 51 GB** (`.sra` format) |
| Total bases | 287,962,940,659 (~288 Gbases) |
| Mean per run | ~426 MB, ~2.4 Gbases |

**Library strategy:**

| strategy | runs | use |
|---|---|---|
| RNA-Seq | **72** | The transcriptomic layer |
| OTHER | 20 | Inspect individually |
| AMPLICON | 16 | Probably not useful |
| **Tn-Seq** | **10** | **Genome-wide fitness screens — potentially the highest-value rows in the set (§4)** |
| WGS | 2 | Strain genomes |

**Organisms:** *S. cerevisiae* 62 · *E. coli* 18 · *Zymomonas mobilis* 12 · *Fusarium graminearum*
8 · *Lactococcus cremoris* 7 · others.

### AMENDMENT 2026-09-20 — the two fetches do not agree, and the difference is not rounding

*What this replaces:* the presentation of the block above as a single measured fact. **120 runs /
51,076 MB** is still exactly what one runinfo fetch returned and is not withdrawn. It is no longer
presented as *the* count.

A second runinfo fetch of the **same query**, on 2026-09-20, returned **~148 runs and ~48.4 GB**.

| fetch | date | runs | total size |
|---|---|---|---|
| A | 2026-09-19 | **120** | **51,076 MB ≈ 51 GB** |
| B | 2026-09-20 | **~148** | **~48.4 GB** |

*Why both are kept.* The two move in **opposite directions** — more runs, fewer bytes — so this is
not simple corpus growth between fetches. Candidate explanations, none verified:

* SRA text search is not deterministic across fetches; the result set drifts as metadata is
  re-indexed (unverified).
* The two fetches resolved different `.sra` storage variants, or one included runs whose size field
  was empty and the other did not. A run with a NULL size contributes to the run count and not to
  the byte total, which produces exactly this signature (unverified).
* Runs were suppressed or re-released between the fetches (unverified).

Picking the larger, the smaller, or an average would all be the same mistake: manufacturing one
number where the evidence supports two. The discrepancy is **itself a datum about SRA text search**,
and it is the reason the rule below exists.

*The rule this imposes on the ingest — binding.* The corpus size is **not** a constant in this
document. The ingest **pins the count at fetch time** and records, per fetch:
`query_string`, `retrieval_timestamp` (UTC), `run_count`, `total_bytes`, `runs_with_null_size`, and
the accession list. Downstream cost and compute estimates cite a **specific fetch**, not "the
corpus". Two fetches that disagree are stored as two rows, and the disagreement is surfaced rather
than resolved — the same treatment section J.4 of PLAN.md gives to conflicting literature claims.

*What does not change.* Both figures round to the same conclusion at the resolution that matters:
**~50 GB, tens of core-hours, single-digit-to-low-double-digit dollars.** No decision in §5, §6 or
§10 turns on 120 vs 148. The reason to record it properly is that a number quoted without its
retrieval time is the kind of fact that later cannot be reproduced or defended.

### Per-organism breakdown of the isobutanol SRA corpus (fetch B, 2026-09-20)

From the fetch-B runinfo. This supersedes the one-line organism tally above, which gave counts
without library strategy and so could not answer "which of these are usable expression data".

| organism | runs | library strategy | what it is for |
|---|---|---|---|
| ***S. cerevisiae*** | **56** | RNA-Seq | The yeast expression layer |
| ***S. cerevisiae* S288C** | **48** | RNA-Seq | Submitted under the S288C label specifically |
| **— yeast RNA-Seq subtotal** | **104** | RNA-Seq | |
| ***E. coli* K-12 MG1655** | **20** | RNA-Seq, OTHER, AMPLICON, WGS | Only the RNA-Seq subset enters the expression layer |
| ***Zymomonas mobilis* ZM4** | **11** | **Tn-Seq**, OTHER | Genome-wide fitness screens |
| ***Fusarium graminearum*** | **8** | RNA-Seq | Screened at paper level; no isobutanol production program |
| ***Lactococcus cremoris*** | **5** | RNA-Seq | Source of `kivD` / `adhA` |

**Correction, and it matters.** The library-strategy table above reports **10 Tn-Seq runs** and
gives the impression, read alongside a yeast-dominated organism tally, that they are yeast. **They
are not. The Tn-Seq runs are *Zymomonas mobilis* ZM4.** §4 of this document calls Tn-Seq
"potentially the highest-value rows in the set" — that judgement stands, but it is a statement
about a **bacterial** fitness screen, and interpreting it requires the *Z. mobilis* genome and
annotation. That is why PLAN.md B.4 now gives the role-3 bacterial hosts a genome and annotation
layer instead of "no genome layer".

**Strain assignment is submitted metadata, not a finding.** The 56/48 split between
"*S. cerevisiae*" and "*S. cerevisiae* S288C" records **what the submitter typed**. The 56 are not
"not S288C", and the 48 are not confirmed S288C. Isobutanol work is done in CEN.PK, in BY-derived
laboratory strains and in industrial backgrounds, and the organism field does not resolve which.
The strain behind each run is curated from the paper, enters as Zone H with its own evidence and
confidence, and `'unknown'` is a legitimate and expected result. PLAN.md F.4 sets out the
consequence: quantify every run against the S288C R64 anchor, and additionally against the CEN.PK
or Ethanol Red proxy where the curated strain warrants it.

*Reconciliation with the counts above.* The listed organisms total 104 + 44 = **148**, matching
fetch B. Fetch A's 120 is 28 fewer and its per-organism split was not retained at the time; the
missing 28 cannot be attributed to particular organisms after the fact. That is recorded as a
limitation rather than reconstructed by subtraction, because subtracting two fetches that disagree
on total bytes would produce a breakdown that looks measured and is not.

### The ratio that justifies the ethanol cap

**147 isobutanol records against 13,117 ethanol records: 89×.** The entire isobutanol omics corpus
is under 1% of the ethanol corpus. Extrapolating the measured 426 MB/run:

| corpus | runs | extrapolated size |
|---|---|---|
| Isobutanol, everything | 120 (fetch A) / ~148 (fetch B) | **51 GB / ~48 GB, both measured** |
| Ethanol reference layer, 6 capped studies | ~60–100 | ~25–45 GB |
| All ethanol + *S. cerevisiae* | 13,117 | **~5.6 TB** |
| All *S. cerevisiae* transcriptomes | 50,626 | **~21.6 TB** |

The cap is worth 5.5 TB and several weeks of processing, for data that would answer a question
you are not asking.

### Two caveats on these counts

**147 is a lower bound.** SRA text search finds only what is in the submitted metadata, and
fermentation metadata is famously sparse — this is risk #1 in PLAN.md W. Studies that deposited
runs without the word "isobutanol" in the metadata are invisible to this query and must be found
paper → BioProject → runs. Budget **~150–250 runs** after paper-driven discovery, not 120.

*(Amended 2026-09-20: "not 120" now reads "not 120–148". The fetch-B result of ~148 runs sits at
the very bottom of this budget range before any paper-driven discovery has happened, which
strengthens rather than weakens the caveat — the query is close to exhausted and the remaining
runs will have to be found through papers.)*

**13 GEO series against 251 yeast isobutanol papers is the more important number.** Roughly 95% of
the isobutanol literature deposited no expression data at all. The omics layer will complement the
literature-derived engineering records; it cannot substitute for them.

---

## 3. Storage, with omics

### Transient (processing)

| item | size |
|---|---|
| Isobutanol SRA, measured | 51 GB |
| Paper-driven additions (~50–100 runs × 426 MB) | +20–40 GB |
| Ethanol reference, 6 studies | +25–45 GB |
| **Total pulled** | **~100–140 GB** |
| If materialized as gzipped FASTQ instead of streamed | ~1.5–2× that ⚠ |
| **Peak working set when streaming 8–16 concurrently** | **~20–40 GB** |

Streaming keeps this a 40 GB problem rather than a 280 GB one. The pattern is already proven in
the sibling project: S3 → named pipe → salmon, with the downloader's exit status checked *after*
salmon finishes, because a truncated gzip otherwise yields a plausible result.

### Retained

| item | size |
|---|---|
| Quantification output + QC (~350 runs × 2–4 MB) | **~1.4 GB** |
| Expression matrices (Parquet) | < 100 MB |
| Structured database (~200–300k rows) | 150–400 MB |
| Sequences (S288C nuclear + mtDNA + parts + proteomes) | ~50 MB |
| Literature text + metadata | ~60 MB |
| PDFs (OA subset, optional) | ~0.9 GB |
| **Total retained** | **~2.7 GB without PDFs, ~4–6 GB with** |

---

## 4. What the omics can and cannot tell you

The part that matters more than the byte counts, and the reason to read §2 carefully.

**72 RNA-seq runs across five organisms is a thin corpus.** After paper-driven expansion, expect
perhaps 100–150 usable RNA-seq runs, of which maybe 60–90 are yeast, spread across a handful of
independent studies.

| question | can the omics answer it? |
|---|---|
| What changes in *this* producer strain vs *its* control? | **Yes** — within-study contrasts are the strength, and this is most of what you want |
| Which genes respond to isobutanol stress? | **Probably** — if the exposure studies use comparable designs |
| Is a response *conserved* across studies? | **Weakly.** Contrast-level meta-analysis over a handful of studies is underpowered for anything but large effects |
| Cross-organism comparison of the producing state | **With caution** — confounded by host, construct and condition simultaneously |
| Which genes limit flux? | **Not directly.** Expression is not flux, and the plan's evidence rules cap correlative omics at L3 |

**The 10 Tn-Seq runs deserve specific attention.** Genome-wide fitness screening under isobutanol
challenge speaks much more directly to tolerance and bottleneck genes than differential expression
does, because it is a perturbation rather than a correlation — L1/L2 evidence under J.3 rather
than L3. Ten runs is a small set, but per-run they are likely the most informative rows in the
whole omics corpus. Prioritise them in phase 4.

**Practical priority order** for the ~350 runs:

1. Paired producer-vs-parent designs in yeast — the direct comparison.
2. Tn-Seq / fitness screens under isobutanol.
3. Isobutanol exposure/tolerance time courses.
4. Cross-host producer transcriptomes.
5. The ethanol reference six, for baseline physiology and the *pdc*-minus background.

---

## 5. Compute

**Correction.** An earlier draft of this document said "15–20 core-hours". That was an arithmetic
error — it confused wall-clock minutes with thread-minutes. The correct figure is below, roughly
6× higher. It does not change any conclusion, because the cost is still small, but the wall-clock
planning depends on it.

| task | cost |
|---|---|
| Salmon index, yeast, decoy-aware, built once | minutes, ~8–16 GB RAM ⚠ |
| Salmon quant, one run (~2.4 Gbases ≈ 20M reads) | ~2–3 min wall on 8 threads ⚠ = **~0.3–0.4 core-hours** |
| `fasterq-dump` / decompression per run | ~0.1–0.2 core-hours ⚠ |
| **~350 runs, end to end** | **~100–150 core-hours** |
| DESeq2 contrasts, enrichment | seconds each |
| Route enumeration and scoring | seconds to minutes |
| Orthology across ~10 proteomes, once | ~1–3 h ⚠ |

Memory: each concurrent salmon process holds a yeast decoy index at ~2–4 GB resident ⚠, so eight
concurrent jobs want ~32 GB. Build the index once and bake it into the AMI or stage it in S3;
rebuilding per run is pure waste.

No GPU. No cluster.

---

## 6. Decision: AWS, because the constraint is connection stability

**Decided 2026-09-20 by the project owner: the local connection is slow and unstable.** That is
the deciding constraint, and it is one no benchmark on this machine could have revealed.

The workstation is otherwise capable — 16 cores, 68 GB RAM, 567 GB free, WSL2 Ubuntu already
running — and would absorb 51 GB and ~36 core-hours in one overnight run. Compute was never the
problem. **Bandwidth is**, and an unstable link does not merely make a 51 GB transfer slow, it
makes it *fail repeatedly and restart*.

### The argument that actually settles it

Earlier I justified AWS on speed. That undersold it. The real point:

> With a server-side `aws s3 cp`, **the 51 GB never traverses your connection at all.** S3 copies
> it from SRA's Open Data mirror into your bucket internally. Your link carries API calls on the
> way in and ~1.4 GB of results on the way out.

A slow, unstable connection is therefore almost irrelevant to the job — which is exactly the
opposite of the local plan, where that connection *is* the pipeline.

Two consequences to design for, both about surviving a dropped link:

* **Nothing interactive.** The job must not be driven from a laptop session that can vanish
  mid-run. Launch it from a `t4g.micro` under `tmux`/`systemd`, or as a user-data script that
  runs and then shuts the instance down. A disconnect must cost nothing.
* **Resumable at every step.** Per-run `run.json` markers so an interrupted batch restarts where
  it stopped, and the staging copy is idempotent so re-running it is safe.

Keep the **content-addressed raw archive** (§6.1) regardless: it is what makes re-quantification
against per-strain references free later, and re-downloading is precisely what this connection
cannot do cheaply.

## 6a. The AWS plan

### The proposed two-phase split: assessment

The proposal — a minimal ARM instance in a US region to fetch SRA and land it in S3, then a
separate right-sized instance for analysis, run for as few hours as possible — is **sound, and
worth doing.** But its justification is not the one it looks like, and one step can be removed
entirely.

**It does not save much money.** Download is I/O-bound and analysis is CPU-bound, so splitting
them avoids paying for idle cores — but at 140 GB that idle time is roughly 30–60 minutes of a
16-vCPU box, about $0.50. That is not the reason to do it.

**The real justification is re-runnability.** Staged raw data in S3 means re-quantifying against a
different index — a per-strain reference, an updated annotation, changed salmon parameters —
costs zero additional retrieval. Given the plan explicitly anticipates moving from a single S288C
reference to per-strain references (PLAN.md F.4), that will happen. **Stage the data because you
will process it more than once, not because it saves compute.**

### The step that can be removed

**For the download leg you may not need an instance at all.** `aws s3 cp` between two S3 buckets
is a **server-side copy** — the bytes never traverse the client, which only issues API calls. So:

```
aws s3 cp --recursive s3://sra-pub-run-odp/sra/<acc> s3://<your-bucket>/raw/<acc>
```

can run from your laptop, or from a `t4g.nano`, and S3 moves the data itself. The SRA Open Data
mirror is in `us-east-1` and is not requester-pays ⚠, so if your staging bucket is also in
`us-east-1` this is free and fast.

That collapses your phase 1 from "cheapest ARM instance" to "no instance", which is cheaper than
cheap and has fewer moving parts.

### The change I would make: stage in `us-east-1`, not `ap-south-1`

Your existing bucket from the sibling project is in `ap-south-1`. Landing the raw there means:

```
SRA (us-east-1) ──140 GB cross-region──▶ your bucket (ap-south-1) ──▶ analysis instance
```

— and then the analysis instance must also be in `ap-south-1` to avoid crossing a *second* time.
That works, and costs about $2.80 ⚠ in transfer. But there is no reason for the raw data to be in
`ap-south-1` at all: it is transient, it is deleted after quantification, and nothing else reads
it.

Better:

```
SRA (us-east-1) ──server-side copy, free──▶ RAW ARCHIVE (us-east-1, permanent)
                                                    │  re-read free, in-region
                                          analysis instance (us-east-1)
                                                    │
                                    ~1.4 GB results ──▶ ap-south-1 bucket
```

One crossing, of 1.4 GB instead of 140 GB. The `ap-south-1` bucket stays the durable home for
derived artifacts — the things you actually browse.

**This matters more now that the raw archive is permanent (§6.1).** Raw that is kept will be
re-read: every re-quantification against a new index reads all 140 GB again. In-region that is
free; from `ap-south-1` to a `us-east-1` instance it is ~$2.80 ⚠ *per re-run*, plus the wall-clock.
Neither figure is large, so this is a preference rather than a constraint — but if the raw archive
lives beside SRA and beside the compute, every future re-run costs nothing to feed.

### 6.1 Decision: the raw archive is permanent

Raw is **retained in S3 indefinitely**, not expired. This reverses the lifecycle-expiry advice in
an earlier draft, and the reasoning changes with it: the archive is no longer a staging buffer, it
is an asset. Re-quantifying against per-strain references, a new annotation or a different tool
then costs no retrieval at all, and the exact bytes that produced any stored result remain
available for audit.

Keep the **`.sra` originals**, not converted FASTQ. They are the compact canonical form (51 GB
measured vs ~1.5–2× that as gzipped FASTQ ⚠), and conversion is only ~0.1–0.2 core-hours per run.
Record the `sra-tools` version in `processing_run` (PLAN.md T.1) so a conversion is reproducible
without storing its output.

**Storage cost, 140 GB ⚠:**

| class | $/GB-month | per month | per year | retrieval fee |
|---|---|---|---|---|
| S3 Standard | ~$0.023 | ~$3.22 | ~$39 | none |
| Standard-IA | ~$0.0125 | ~$1.75 | ~$21 | ~$0.01/GB |
| **Intelligent-Tiering** (settles in Archive Instant Access after 90 days) | ~$0.004 | **~$0.56** | **~$7** | **none** |

**Use Intelligent-Tiering.** With ~350 objects the monitoring charge is negligible, objects are
far above the 128 KB threshold where monitoring applies, and the Frequent → Infrequent → Archive
Instant Access transitions carry no retrieval fee ⚠. It needs no lifecycle tuning and no decision
about access patterns you cannot predict. This supersedes the earlier "do not bother with tiering"
note, which assumed the data would be deleted within weeks.

**Two things to add now that the archive is durable:**

* **Checksums.** Store each object's ETag/MD5 alongside the accession. Content addressing is
  already a convention (CONVENTIONS.md, T.2); for data you intend to still trust in three years it
  is the difference between an archive and a directory.
* **A `raw_object` table** mapping run accession → bucket, key, size, checksum, retrieval date and
  source URL. The provenance chain (J.5) should reach the bytes, not stop at the accession.

**Reconciling with decision 11.** PLAN.md decision 11 says "FASTQ is transient". That still holds
and does not conflict: the `.sra` archive is permanent in S3, while FASTQ is never materialized to
disk at all — it is streamed through a pipe into the quantifier and never written. Permanent
compact archive, transient expanded form.

### 6.2 The download instance

Server-side `aws s3 cp` means the instance issues API calls and never touches the bytes, so it can
be the smallest thing available:

| instance ⚠ | vCPU | RAM | ~$/h | notes |
|---|---|---|---|---|
| **`t4g.nano`** | 2 (burstable) | 0.5 GB | **~$0.0042** | Enough for S3→S3 orchestration. Total cost for the campaign: **under 2 cents** |
| `t4g.micro` | 2 | 1 GB | ~$0.0084 | Safer headroom for aws-cli v2 with many concurrent multipart copies; still under 4 cents |

Recommend **`t4g.micro`** — the extra 2 cents buys RAM headroom that 0.5 GB does not comfortably
give the CLI when several multipart copies run at once.

Practical notes:

* Run under `tmux`/`systemd`, or give it a user-data script that copies then calls
  `shutdown -h now`, so a disconnected session does not leave it running.
* **Instance network bandwidth is irrelevant for the S3→S3 leg** — the bytes move inside S3. It
  only matters if some accessions must be pulled over HTTP from ENA instead, in which case use
  `m7g.medium` (~$0.041/h ⚠) for that subset, since `t4g` baseline network is low and burst
  credits deplete over a 140 GB transfer.
* Two zero-instance alternatives, if you ever want them: **AWS CloudShell** (free, has the CLI, but
  idles out after ~20 minutes so it suits short batches), and **S3 Batch Operations** with a
  manifest (~$0.25 per job + $1 per million objects ⚠ — fully managed, nothing to babysit).

### ARM: fine for the copy, verify before the analysis

Graviton is the right default for anything I/O-bound, and if the download leg becomes a nano
instance the architecture is irrelevant anyway.

**For the analysis instance, check aarch64 availability before committing.** Bioconda's
`linux-aarch64` channel is substantially smaller than `linux-64`, and salmon, fastp and sra-tools
may not all have ARM builds ⚠. Running amd64 containers on Graviton under emulation would erase
the price advantage several times over. Test the toolchain on a `t4g.micro` for ten minutes before
sizing the real instance — if it builds, Graviton is ~10–15% cheaper per core-hour ⚠; if it does
not, use `c7i` and lose nothing that matters at this scale.

### Sizing: there is almost no cost/time trade-off to balance

This is the useful part of the answer. You are buying **core-hours**, and the price per core-hour
is roughly flat across instance sizes in a family. So the total is nearly invariant and only the
wall-clock changes:

| instance ⚠ | vCPU | ~$/h on-demand | wall for ~120 core-h | campaign cost |
|---|---|---|---|---|
| `c7g.4xlarge` (ARM) | 16 | ~$0.58 | ~8 h | ~$4.60 |
| `c7g.8xlarge` (ARM) | 32 | ~$1.16 | ~4 h | ~$4.60 |
| `c7i.8xlarge` (x86) | 32 | ~$1.43 | ~4 h | ~$5.70 |
| **`c7i.16xlarge` (x86) — chosen** | **64** | **~$2.86** | **~2 h compute, ~3 h realistic** | **~$8–9** |

**Pick the size for the wall-clock you want, not for the price.** The only lever that actually
moves the cost is **spot**, which is roughly 60–70% off ⚠.

### 6.3 Running the chosen 64-core instance

`c7i.16xlarge`: 64 vCPU, 128 GB RAM, up to 25 Gbps network ⚠. Memory and network are both
comfortable — with 16 concurrent salmon processes at 2–4 GB resident each, 128 GB is
over-provisioned, and S3 reads will not bottleneck.

Three things follow specifically from choosing 64 cores:

1. **Run 16 jobs × 4 threads, not 8 × 8.** Salmon scales sub-linearly past roughly 8 threads ⚠, so
   more parallel jobs with fewer threads each gives better aggregate throughput on a wide machine.
2. **Budget ~3 hours, not 2.** At 64 cores the non-parallel overhead becomes a large fraction of
   the total: instance boot, environment setup, index build, and the tail where only the last few
   long runs are still going. This is the diminishing-returns point — which is fine, since the
   instance was chosen for speed, but the estimate should be honest.
3. **Use on-demand, not spot.** Large instances have thinner spot capacity and higher interruption
   rates ⚠, and the saving on a three-hour job is about $6. The pipeline is resumable so spot
   would be *safe*, but paying $6 to remove interruption handling from a job you will run a
   handful of times is the right trade. Spot becomes worth it only if this becomes routine.

### Costed, end to end

| line | estimate ⚠ | frequency |
|---|---|---|
| Download instance, `t4g.micro`, ~3 h | **~$0.03** | once |
| S3→S3 server-side copy, same region | **$0** | once |
| Analysis instance, `c7i.16xlarge` on-demand, ~3 h | **~$8.60** | per processing campaign |
| EBS gp3 root + modest scratch, few days | ~$1–2 | once |
| Cross-region transfer of results (~1.4 GB) | ~$0.03 | per campaign |
| **One-off total** | **~$10** | |
| **Raw archive, 140 GB, Intelligent-Tiering** | **~$0.56/month (~$7/year)** | ongoing |
| Derived artifacts, ~5 GB | ~$0.12/month | ongoing |

So: **about $10 to run it, and about $8 a year to keep it.** A re-quantification later is another
~$9 of compute and nothing in retrieval, which is exactly what retaining the archive buys.

### Configuration notes

* **Intelligent-Tiering on the raw prefix** (§6.1). No expiry — the archive is permanent by
  decision.
* **Bake the salmon index into the AMI** or stage it in S3. Rebuilding per run is pure waste, and
  on a 3-hour job the index build is a visible fraction of it.
* **Store checksums and a `raw_object` row per run** so provenance reaches the bytes, not just the
  accession.
* **Keep the database local.** At 150–400 MB it belongs on your machine, not behind a network
  round-trip. Only bulk artifacts go to S3.
* **Check the downloader's exit status *after* the quantifier finishes.** A truncated stream still
  produces a plausible salmon result — a recorded failure mode from the sibling project, not a
  hypothetical.
* **Tag both instances and the buckets** with a project tag from the start, so the ongoing $8/year
  is attributable when you look at a bill in a year and wonder what it is.

### Is AWS necessary?

Not for scale — 140 GB and ~120 core-hours is a laptop weekend with a decent connection. The real
arguments are in-region retrieval speed, not tying up your working machine, and a pinned image
being a more reproducible environment than a laptop. Those are good reasons; scale is not one of
them, and it is worth knowing so the infrastructure does not grow to justify itself.

AWS becomes genuinely *necessary* only if the ethanol cap is lifted (5.6 TB) or the full
*S. cerevisiae* transcriptome is ingested (21.6 TB).

---

## 7. Structured database

Unchanged by the omics layer except for sample and quantification metadata.

| table | rows |
|---|---|
| publication (incl. exclusions with reasons) | ~3,500 |
| extraction + span | ~12,000 + ~30,000 |
| strain | ~1,500–2,500 |
| modification | ~5,000–8,000 |
| measurement | ~8,000–12,000 |
| condition_context | ~2,500 |
| pathway_configuration | ~250–400 |
| part + expression_record | ~150 + ~600 |
| reaction + metabolite | ~500 + ~400 |
| gene + gene_group | ~6,300 + ~6,500 |
| assertion + evidence_item | ~20–40k + ~40–80k |
| pathway_route (materialized, §8) | ~20,000 |
| **sample + quantification + de_result** | **~350 + ~350 + ~2M (Parquet, not rows)** |
| **Total relational** | **~200,000–300,000 rows → 150–400 MB** |

Expression values go to Parquet, not to the database: ~6,000 gene groups × ~350 samples is 2.1M
values, which is ~10 MB as a float32 columnar matrix and several hundred MB as relational rows.

---

## 8. The real blow-up risk: route combinatorics

Not storage. Naive enumeration:

```
5 steps × ~4 candidate parts each        ≈ 1,000 enzyme combinations
× 5 coherent compartment strategies      ≈ 5,000
× 4 cofactor strategies                  ≈ 20,000
× powerset of ~10 candidate deletions    ≈ 20,000,000
```

**Mitigation, a design decision not an optimization: deletions are a ranked overlay on a core
route, not a combinatorial dimension.** Enumerate the ~20,000 enzyme × compartment × cofactor
cores, score those, attach a ranked deletion recommendation to each. 20,000 scored routes at ~1 KB
is 20 MB. Enumerate lazily and prune at the first failing gate rather than generate-then-filter.

---

## 9. Curation hours — still the binding constraint

| activity | estimate |
|---|---|
| Screening review (~600 borderline × 2 min) | ~20 h |
| Deep extraction, ~350 quantitative papers × 30 min | **~175 h** |
| Lighter review, ~450 papers × 10 min | ~75 h |
| Pathway, parts, compartment curation | ~80 h |
| Mitochondrial corpus | ~60 h |
| Ethanol reference layer | ~40 h |
| **Omics condition annotation, ~350 runs × ~8 min** | **~47 h** |
| **Total** | **~500 hours ≈ 12–13 weeks of pure curation** |

Omics adds ~47 hours, and the annotation is not optional: PLAN.md F.3 makes condition annotation
gate quantification, because a quantified run with unknown conditions is a column that cannot
enter any comparison. At 350 runs that is about six working days.

Levers if it overruns, in order: narrow hosts to *S. cerevisiae* + *E. coli*; drop adjacent
higher-alcohol capture; sampled rather than exhaustive review with the rate recorded; defer the
ethanol layer to an E1-only minimum (~15 h).

---

## 10. Hardware verdict

**Local:** any current laptop. 16 GB RAM, 50 GB free. The database, the literature and the
analysis all live here comfortably.

**AWS:** one 8–16 vCPU instance in `us-east-1` for roughly one day, plus a few GB of S3. Under
$25 for the campaign.

The workstation specification in PLAN.md V.5 (32 cores, 128 GB, 20 TB) remains overkill by two
orders of magnitude, and becomes relevant only if the ethanol cap is lifted.
