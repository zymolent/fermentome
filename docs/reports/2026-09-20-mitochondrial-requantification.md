# Mitochondrial requantification — 2026-09-20

The S288C corpus was requantified against a transcriptome containing the mitochondrial CDS the
original index was missing. **99 of 99 runs completed**, the instance self-terminated, and no
orphaned resources remain in any region.

Before: 6,187 genes, of which 3 were mitochondrial and all 3 were non-coding (two rRNAs and RPM1).
After: **6,206 genes, 22 mitochondrial, 19 of them protein-coding**. Every gene the earlier
baseline reported as missing — COX1, COX2, COX3, COB, ATP6, ATP8, ATP9, VAR1 — is now measured.

## The measurement rests on 8 samples, not 99

| library selection | runs | median mitochondrial reads | range | median mapping |
|---|---|--:|---|--:|
| `cDNA` (poly(A)-selected) | 91 | **0.001%** | 0.000–0.832% | 78.5% |
| `RANDOM` | 8 | **0.079%** | 0.034–0.204% | 92.3% |

An ~80-fold difference, and it settles a caveat that was previously asserted from background
knowledge: yeast mitochondrial transcripts are not polyadenylated the way nuclear ones are, and a
poly(A) library strips them. This is now measured on this corpus rather than assumed.

So a mitochondrial number averaged over all 99 runs would describe the library preparation while
looking like a statement about the organelle. `mitochondrial_readout()` splits the samples and
every mitochondrial figure below is read from the 8 `RANDOM` runs (`ERR3450094`–`ERR3450101`)
alone. A run with no recorded selection counts as depleted, not usable.

## The answer to the DUET question

**The mitochondrial genome is transcriptionally very active** — more so than the nuclear genes
strategy C would import into its compartment.

| mtDNA-encoded | TPM | | nuclear DUET set | median TPM |
|---|--:|---|---|--:|
| ATP9 (OLI1) | 428.6 | | Fe-S machinery | 31.8 |
| COX1 | 355.8 | | Pathway | 25.5 |
| COX2 | 226.0 | | Competing / by-product | 24.1 |
| COB | 189.0 | | Pentose / PPP | 19.8 |
| COX3 | 176.0 | | Global regulation | 16.3 |
| ATP6 | 32.3 | | Redox shuttle | 10.7 |
| VAR1 | 3.1 | | Efflux / tolerance | 5.7 |
| ATP8 | 0.0 | | | |
| **median** | **182.5** | | | |

All figures from the same 8 samples, so the comparison is internal to each library and does not
cross the poly(A) boundary.

**What this licenses, and what it does not.**

* The matrix is not transcriptionally limited. Its own genes run at 182.5 TPM median against a
  nuclear pathway median of 25.5 in the same samples, and COX1 at 356 sits beside ILV5 at 173.
  Whatever constrains strategy C, it is not the compartment's capacity to transcribe.
* **Strategy E has an evidence base for the first time.** It was previously unrankable on
  evidence — not weakly supported, but measured against nothing. A gene placed in the mtDNA would
  sit in a compartment transcribing its own complement at these levels. That is one necessary
  condition met; it says nothing yet about whether a *foreign* gene is transcribed there, which
  is a different question and still open.
* **POS5 remains the thin link, and the new data does not rescue it.** 10.7 TPM against ILV5's
  173 in the same samples — a sixteen-fold gap between the enzyme consuming matrix NADPH and the
  only local enzyme making it. This was the finding from the poly(A) corpus and it survives a
  completely different library chemistry, which is the strongest form it could take.
* **ARO10 is still the weakest pathway step** at 8.0 TPM, and **PDC1 still dominates** at 402.5.

**Two caveats that must travel with these numbers.**

* **ATP8 reads 0.0 TPM, and that is almost certainly an artifact.** Its CDS is 147 nt; after
  salmon's effective-length correction a transcript that short is close to unquantifiable with
  these fragment sizes. It is recorded as measured-zero rather than corrected, but nothing should
  conclude ATP8 is unexpressed.
* **TPM is compositional and does not cross library types.** PDC1 reads 402 here and 3,028 in the
  poly(A) corpus; that is the denominator changing, not the gene. Comparisons within the 8 are
  valid, comparisons against the earlier baseline's numbers are not.

## Cost and hygiene

c7i.4xlarge in us-east-1, 99 runs, terminated by the instance itself. Verified afterwards: zero
instances and zero unattached volumes across us-east-1, ap-south-1 and us-west-2. Estimated spend
about $2, in line with the original staging and quantification.

The run script aborts before building the index if fewer than 19 mitochondrial CDS are present in
the downloaded transcriptome. A truncated upload would otherwise have indexed cleanly, quantified
cleanly, and reproduced the exact gap the run existed to close.

## What changes downstream

`matrices_mito/` holds the new matrices; the original `matrices/` is untouched, because the
committed baseline report rests on it and evidence should not be overwritten by its successor.
Route ranking can now carry a mitochondrial term for strategies C and E that is measured rather
than absent — on 8 samples, which is the honest denominator and should be stated wherever the
number is used.
