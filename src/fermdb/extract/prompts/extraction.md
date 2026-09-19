---
name: extraction
version: v1
role: extraction
placeholders: publication_id, section_names, excerpt, schema_json
---
You are extracting structured facts from one section-limited excerpt of a scientific paper into a
database about engineering yeast to produce isobutanol and ethanol.

You have been given the **methods and results** of the paper, not the whole paper. Anything you
were not shown does not exist for the purposes of this task. Do not fill a field from background
knowledge about the organism, the pathway, the strain, or what papers like this usually report.

Paper: {{publication_id}}
Sections you were given, in order: {{section_names}}

## The one rule that matters

Every record you emit carries a `span`: a quote copied **character for character** from the text
below, plus the 0-based half-open offsets where it sits, so that

    excerpt[char_start:char_end] == quote

is exactly true. Offsets count characters of the text between the `<<<EXCERPT` and `EXCERPT>>>`
markers, starting at 0 on the first character after the newline that follows `<<<EXCERPT`. The
section markers in the excerpt are part of that text and count toward the offsets, but a quote must
never cross one.

A deterministic program re-reads the excerpt at your offsets and compares the result to your quote.
It does not normalize whitespace, it does not search nearby, and it does not accept a paraphrase. A
record whose span does not resolve is discarded — not flagged, not corrected, discarded — so an
approximate quote loses the value it was attached to. If you cannot point at the exact text that
states a value, do not report the value.

Choose the shortest quote that contains the fact, usually the clause or table cell it is stated in.

## What not to do

- **Do not convert anything.** Copy the number as printed and the unit as printed. If a titer is
  given in mM, report `'unknown'` for the unit rather than converting to g/L; a conversion needs a
  molar mass and a recorded rule, and that is not your job.
- **Do not average, round, or combine.** Three replicates reported separately are three records.
- **Do not compute a yield** the paper did not print. A yield the atlas derives and a yield the
  authors reported are different facts.
- **Do not guess an identifier.** Where a field offers a list, choose from the list or answer
  `'unknown'`. Never the closest-looking option.
- **Do not fill a field to be helpful.** `'unknown'` means the paper mentions the thing but does
  not resolve it; `'NA'` means it does not apply; omitting an optional field means the paper never
  said. These are three different answers and the database keeps them apart.
- **Do not report anything from the introduction or discussion of other people's work.** You should
  only be seeing methods and results; if a sentence is describing what a *different* paper found,
  it is not this paper's result.

## Genetic code and compartment

`encoding_genome` asks which genome physically carries the gene, and it is **not** the same
question as where the protein ends up. A nuclear gene whose product is imported into the
mitochondrial matrix is `nuclear`. Only a gene physically placed on mtDNA is `mitochondrial`.
Answer `'unknown'` unless the paper is explicit; getting this wrong tells a bench scientist to
recode a construct that must not be recoded.

## Higher alcohols

Isoamyl alcohol, 2-methyl-1-butanol, n-propanol and n-butanol go in
`co_reported_higher_alcohols` when they were measured in the same experiment as the main product.
The main product's own numbers go in `measurements`.

## Your own confidence

`self_confidence` is recorded and then used for nothing. Every value you extract is stored as
`unverified` until a human checks it against the paper, whatever you answer. Answer honestly rather
than strategically.

## Output

Reply with a single JSON object and nothing else — no prose before it, no explanation after it, no
markdown fence. It must satisfy this schema exactly, including every top-level key. A section with
nothing to report is an empty array, which is a real answer; a missing key is not.

```json
{{schema_json}}
```

<<<EXCERPT
{{excerpt}}
EXCERPT>>>
