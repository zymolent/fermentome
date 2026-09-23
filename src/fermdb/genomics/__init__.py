"""Genome-scale gene models: the RefSeq GFF3 a whole annotation arrives in, and its loader.

`fermdb.omics.genes` resolves a *named* gene set -- the 36 symbols DUET_TARGET.md §3 asks for --
out of a transcript FASTA, one symbol at a time, and refuses to guess when a symbol is absent.
That is the right shape for a curated panel and the wrong shape for an annotation: it can only
find genes somebody already thought to name, so the other ~6,570 genes of S288C are invisible to
every query the atlas can ask. A gene that is not in the table cannot be the answer to "which
genes sit in this QTL interval", "what else is on the mitochondrial genome", or "is this hit even
protein-coding" -- and the absence looks exactly like a negative result.

So this package does the complementary job: take the annotation whole, as the source states it,
and let the curated panel keep its own provenance. The two meet on the same ids
(`YAA:GENE:<assembly-slug>-<locus-tag>`) and the same `gene_group` anchors, which is what makes
"a paper says ADH2, the atlas keys on YMR303C" work for a gene nobody curated by hand.

Everything here is Zone R -- a verbatim parse of a checksummed RefSeq file, with the single
transformation CONVENTIONS.md mandates at a parser boundary (1-based inclusive in, 0-based
half-open out). Nothing in this package infers, models or guesses, and `load_genes` never
overwrites a value a curator put there.
"""

from __future__ import annotations
