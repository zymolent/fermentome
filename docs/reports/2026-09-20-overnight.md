# Overnight run — 2026-09-20

Unattended session, in two parts.

**Session 1** ran with **no EC2 instance at all** — the 111.9 GB staged itself server-side inside
S3. **Session 2** launched quantification after the owner confirmed a small instance was
acceptable. Instance count was verified before, during and after every step.

Read this document top to bottom: session 1 below, session 2 from "Session 2" onward. Where the
two disagree, session 2 is later and wins — in particular, session 1's "needs you present" and
"needs your decision" lists were largely resolved in session 2 and are marked where they were.

---

## Deliverables

### 1. The isobutanol SRA corpus is staged in S3 — complete

```
s3://fermdb-raw-211125789985/raw/sra/
172 objects · 111,893,392,481 bytes (111.9 GB) · 0 failures · 5.7 minutes
```

Verified against S3 itself, not against the script's own claim. Every object landed in
`INTELLIGENT_TIERING`, so storage settles at roughly **$0.14/month** once tiered.

**No instance was needed.** `aws s3 cp` between buckets is server-side: one probe copied 150 MB in
6.2 s using **0.015 s of local CPU**, proving the bytes never traverse this machine. The slow,
unstable local connection is therefore irrelevant to this step — which was the original argument
for AWS, now measured rather than asserted.

### 2. Reference genomes fetched and verified

In `~/fermdb-data/genomes/`, with SHA-256 recorded:

| reference | accession | sequences | size |
|---|---|---|---|
| S288C (anchor, **incl. mitochondrion**) | `GCF_000146045.2` | 17 | 12.16 Mb |
| CEN.PK113-7D (physiology comparator) | `GCA_002571405.2` | 18 | 12.08 Mb |
| Ethanol Red (industrial proxy) | `GCA_029255905.1` | 157 | 11.52 Mb |
| *E. coli* K-12 MG1655 | `GCF_000005845.2` | 1 | 4.64 Mb |
| *Z. mobilis* ZM4 | `GCF_004168305.2` | 5 | 2.20 Mb |
| *L. cremoris* KW2 | `GCF_000468955.1` | 1 | 2.43 Mb |

### 3. The compartment model is validated against real data

The mitochondrial genome `NC_001224.1` (85,779 bp) was pulled with its 18 annotated CDS and
their NCBI protein translations, and each was re-translated with `fermdb.genetic_code`:

```
TABLE 3 (yeast mitochondrial): 18/18 match
TABLE 1 (standard)           :  0/18 match
```

This is the first time the genetic-code model has been checked against anything other than
itself. It also confirms the mtDNA gene set that `MITOCHONDRIAL_PROGRAM.md` carried as ⚠:
COX1/2/3, COB, ATP6, ATP8, OLI1 (ATP9), VAR1, plus the COX1/COB intronic maturases (AI1–AI5,
BI2–BI4) and the I-SceI homing endonuclease.

### 4. Code

625 tests (from 500), ruff/format/mypy clean, `SCHEMA_VERSION` 4. Committed as `7d76fa4`.

DUET scope corrections landed in `PLAN.md`; per-organism reference selection; escalation via the
Claude Code subscription; the functional annotation layer for yeast and bacterial hosts; **E6**
(the Ethanol Red question) wired through parser, schema `CHECK` and query families; and the
seven-slot ethanol reference design.

---

## Four errors caught, and how

Worth recording because the pattern is consistent: **each was caught by checking a result against
an independent expectation, not by any test.**

| error | how it was caught | consequence if missed |
|---|---|---|
| **A reference genome was the wrong organism.** `GCF_000092685.1`, written from memory as *Z. mobilis* ZM4, is *Chlamydia trachomatis* | Sequence length 1.04 Mb against an expected ~2 Mb | A Chlamydia genome sitting in the reference set labelled *Z. mobilis*, silently corrupting any bacterial comparison |
| **The entire curated layer was untracked.** `.gitignore` had `env/` under "Virtual environments" and ignored `data/` wholesale | `git check-ignore` while storing the API key | Vocabularies, benchmark set and query families existed only in the working tree across two commits. A `.gitignore` has no tests, so every gate stayed green |
| **The corpus size was wrong by 2×.** Earlier "measured" figures of 51 GB and 48 GB came from a small model summarising a large CSV | Summing the CSV locally in Python: 172 runs, 104 GB by metadata, 111.9 GB actual | Storage and compute planning off by half |
| **`SCHEMA_VERSION` unbumped** after eight tables were added | The review agent | A phase-0 database accepted as current, then failing at query time |

The third is mine to own: I presented model-summarised numbers as *measured*, which is exactly
what this project's own conventions say to distrust.

---

## Cost

| item | actual |
|---|---|
| S3 PUT requests, 172 objects | fractions of a cent |
| Storage, 111.9 GB Intelligent-Tiering | **~$0.14/month** once tiered (~$2.57/mo at Standard before transition) |
| Data transfer | **$0** — in-region, server-side |
| EC2 | **$0 — no instance launched** |

---

## Ready to run, needs you present  *(both done in session 2)*

**Quantification.** — DONE, running on `i-088fe14f1c19eec92`. Original note kept for the record: 117 RNA-Seq runs across five organisms. This is the step that needs an
instance, and I deliberately left it: unattended it has too many first-run failure modes
(toolchain install, five indexes, per-organism reference selection). When launched it will be
self-terminating — `terminate-on-shutdown` plus a hard internal timeout — so it cannot run away.
Estimated ≤ $10.

**Literature discovery.** — DONE, 5,164 publications. Original note: The API key works (verified; 147 SRA, 1,027 PubMed isobutanol). Not run
yet because the modules were being rewritten under me for most of the session. It is a single
command now.

---

## Needs your decision

1. **RESOLVED in session 2 — sub-budget accepted.** E5 45 / E6 25 / E1 25 / E2 20 / E3 20 /
   E4 15 = 150, recorded in `docs/reference/ETHANOL_REFERENCE_SLOTS.md`. Original text:
   **The ethanol cap conflicts with E5.** E5's outer bound is 642 publications against a
   ~150-publication total cap. A review agent proposed splitting it E5 50 / E1 30 / E2 25 /
   E3 25 / E4 20 — and that was before E6 existed, so it needs a seventh share. Without an agreed
   sub-budget, E5 consumes the cap and E1–E4 arrive empty.
2. **RESOLVED in session 2 — accepted as proxy, limitation acknowledged.** Original text:
   **Ethanol Red is scaffold-level only** (N50 189 kb). Accept that structural variants and
   subtelomeres are not callable from it — which is where industrial adaptations are often
   reported (unverified) — or treat it as a stated proxy and plan to sequence your own strain.
3. **Eight *F. graminearum* runs** are flagged `relevance_uncertain` as a likely keyword false
   positive. Confirm they are out and I will drop them rather than fetch a Fusarium genome.
4. **M4** (GC panel) remains open; the by-product design is optional so it does not block.

---

# Session 2 — quantification, literature, extraction

## Delivered since the report above

**Literature corpus discovered: 5,164 unique publications** (6,381 screening records,
deduplicated), 9 search runs, every family landing exactly on its baseline.

| family | records | |
|---|---|---|
| ethanol_scerevisiae_prod_ferm_tol | 1,423 | needs_full_text |
| isobutanol_all | 1,309 | included |
| mtdna_methods_yeast | 1,298 | included |
| **mtdna_engineering_yeast** | **912** | included |
| isobutanol_production | 649 | included |
| ethanol_mitochondria_yeast | 504 | needs_full_text |
| isobutanol_yeast | 257 | included |
| **isobutanol_mitochondria** | **29** | included |

The asymmetric policy is visibly working: 4,454 isobutanol/mtDNA records default to `included`,
while all 1,927 ethanol records sit in `needs_full_text` awaiting admission under E1–E6. None
silently admitted.

**The extraction chain works end to end on a real paper.** Against `avalos2013.pdf` the local
27B model returned *"Compartmentalization of the Ehrlich pathway into mitochondria increased
isobutanol production by 260%"*, the span resolved against the source, and a fabricated control
quote was rejected. That independently confirms the 260% figure this project had carried as ⚠.

**Matrix assembler validated** on live output: 6,187 genes × 10 samples, median 5,985 genes
detected, median 78.3% mapping, 10/10 above the QC floor.

## Three more silent-failure bugs

| bug | would have looked like |
|---|---|
| `--gencode` on the salmon index split NCBI headers on `\|`, naming all 6,187 transcripts `lcl` | a valid matrix with every gene collapsed into one row |
| `esummary` joined a whole family's ids into one GET URL (~12 kB) | HTTP 414 — the honest one. The dry run missed it because dry run issues only `esearch`, which returns no id list |
| the local 27B model returns an **empty string**, not an error, whenever `format` is used | *"this paper contains no facts"* — across a whole corpus |

Running total: **eight bugs tonight, none of which announced itself**. Each was caught by
checking a result against an independent expectation — a sequence length, a `git check-ignore`,
a mapping rate, a hit count, a response length. None by the test suite as it stood; tests were
added after each.

## Fixes that outlive tonight

* `canonical_source_text()` — spans are recorded against whitespace-canonical text, so a verbatim
  PDF quote verifies **without** weakening `verify_span`'s exact comparison.
* Measured local-model compatibility table in `MODEL_ROUTING.md` §7b, with `providers.py` holding
  only a pointer (an existing test forbids model names outside the defaults table — and it caught
  me writing them into a comment).
* `esummary`/`efetch` chunk at 200 ids.
* Query baselines re-measured against the queries that actually ship, so drift detection compares
  like with like for the first time.

## Cost

**~$0.85 total.** 172 objects staged for ~$0 (server-side), one c7i.4xlarge at $0.714/h.
Instances verified at every step; the first instance proved the safety design by terminating
itself rather than idling.

---

# Final: quantification complete

## 109/109 runs quantified, 0 failures

The instance terminated itself on completion. Final safety sweep: **0 instances in any state**
across us-east-1, ap-south-1, us-west-2, eu-west-1, eu-central-1; **0 orphaned volumes**.

## Expression matrices

In `~/fermdb-data/matrices/` and mirrored to `s3://fermdb-raw-211125789985/matrices/`:

| reference | genes | samples | median genes detected |
|---|---|---|---|
| **S288C** | 6,187 | **99** | 5,808 |
| *E. coli* K-12 MG1655 | 4,440 | 6 | 4,044 |
| *L. cremoris* KW2 | 2,325 | 4 | 1,928 |

Counts and TPM are written **separately per organism and never concatenated** — they are
different reference spaces, and a combined matrix would be a category error.

## QC: the gate earned its place

Median mapping **78.6%**, 105/109 at or above the 50% accept floor.

| band | runs | |
|---|---|---|
| **< 35% — reject** | 2 | `SRR29711605` (9.6%), `SRR29711606` (9.7%), both *E. coli* |
| 35–50% — flag | 2 | `SRR16481348` (47.1%), `SRR16481350` (49.9%), yeast |
| ≥ 50% — accept | 105 | |

Per reference: *L. cremoris* median 88.0%, S288C 78.6% (47.1–94.4), *E. coli* 54.4% (9.6–55.0).

**The two rejects are worth a human look rather than a silent drop.** They are consecutive
accessions from one study, 18.8M reads each, and map at 9.6% against *E. coli* MG1655 while the
other four *E. coli* runs sit at 54–55%. A tenfold gap within one organism is not a quality
gradient — it suggests those two are a different organism, a different strain, or not the library
type their metadata claims (unverified). Recorded in `qc.tsv`, excluded from analyses, not deleted.

*E. coli*'s 54% median is itself lower than yeast's and is expected: bacterial total-RNA libraries
without rRNA depletion map poorly onto a CDS+ncRNA reference (unverified). Not a defect, but it
means *E. coli* and yeast mapping rates are not comparable to each other.

## One more latent bug, found while assembling

The matrix build failed part-way with `Could not connect to the endpoint URL:
...s3.ap-south-1.amazonaws.com`. The bucket is in **us-east-1**; the CLI default profile is
**ap-south-1**; with no explicit `--region`, the CLI built a wrong-region endpoint. Earlier calls
had survived on S3 redirects, which is what makes this the bad kind of bug — it works most of the
time. Region is now pinned explicitly and every call retries with backoff.

## Final cost

| | |
|---|---|
| EC2 | ~3 h `c7i.4xlarge` @ $0.714/h + a 35-min failed first attempt ≈ **$2.10** |
| S3 storage, 112 GB Intelligent-Tiering | ~$0.14/month once tiered |
| Transfer, requests | pennies |
| **Total spent** | **≈ $2.10** against a $10 ceiling |

Nothing left running.
