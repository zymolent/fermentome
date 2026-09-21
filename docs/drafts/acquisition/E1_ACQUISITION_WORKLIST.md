# E1 acquisition worklist — the 52 papers the counterfactual layer cannot read

**DRAFT, 2026-09-22.** Nothing was written to `data/` and nothing to the database. No `confidence`
value is set, no `verified` bit is flipped, no record is admitted. `fermdb extract` was not run.
The machine-readable form is `E1_worklist.tsv` beside this file.

E1's shortfall is not scarcity. PHASE2_STATUS.md §4 states it exactly: **three-quarters of the
criterion is identified and unreadable**, and the 22 unspent budget lines are unspendable by
construction until this queue is worked. This is the queue, ordered by what would actually change
what E1 can say.

---

## 1. The count, live from the database

| | |
|---|---|
| publications tagged E1 | **69** |
| readable (`fulltext_asset.storage_state = 'stored_fulltext'`) | **17** |
| on the manual download queue, `status = 'pending'` | **52** |
| — paywalled | 25 |
| — licence forbids redistribution | 14 |
| — no PDF found | 11 |
| — fetch failed | **2** |

17 + 52 = 69.

### Two corrections to PHASE2_STATUS.md §4, which this pass found by recounting

* §4 reports **68 tagged / 16 readable**. The live counts are **69 / 17**. One more E1 paper has
  become readable since that table was written; the queue total of 52 is unchanged, so the
  arithmetic still closes, one row further along.
* §4's breakdown reads "52 on the manual download queue (25 paywalled, 14 licence-forbidden,
  11 no PDF found)". **Those three numbers sum to 50, not 52.** The missing two are
  `why_unavailable = 'fetch_failed'`, a fourth category the schema has and that summary dropped.
  They are ranked 31 and 41 below and are flagged, because a `fetch_failed` row is the one kind
  of entry on this list that **does not need the owner at all** — the automated retrieval errored
  rather than being refused, so re-running `fermdb literature acquire` for those two is worth
  trying before anyone opens a browser.

---

## 2. Why the existing exporter was not enough

`fermdb literature manual-queue export --out queue.tsv` exists and runs, but it does not fit this
request for two reasons, both of which are properties of the data rather than of the command:

1. **It has no criterion filter.** It exports every `pending` row — **3,735** of them across the
   whole corpus. The 52 E1 rows are not separable from its output without a join back to
   `screening_record.admitted_criterion`.
2. **Its ordering collapses on this set.** `export_queue` sorts by `priority ASC`, and
   `priority` is `acquire.compute_priority`'s output, which ranks by topic tier and then by
   whether the paper reports a titer or yield. For these 52 rows:

   | `priority` | `priority_topic` | `reports_titer_or_yield` | rows |
   |---|---|---|---|
   | 8 | ethanol | NULL | 1 |
   | 10 | other | NULL | **51** |

   Every row but one is `other`/`NULL`, so 51 of 52 tie at priority 10 and fall through to the
   `year ASC` tiebreak. That is not a prioritisation; it is an alphabetical accident. The cause is
   benign and is documented in `acquire.py` itself: `classify_topic` reads the title, these titles
   say "lactic acid" and "2,3-butanediol" rather than "ethanol", and `reports_titer_or_yield` is
   correctly `NULL` because by construction nobody has read the paper yet. **The column is not
   wrong; it is just not informative here.**

So the output is extended rather than replaced. `E1_worklist.tsv` carries every column the
built-in exporter would have written — `doi`, `pmid`, `title`, `journal`, `year`,
`publisher_url`, `best_known_link`, `why_unavailable`, and the computed `priority` /
`priority_topic` so nothing is lost — plus four this task needs:

* `rank` — 1–52, most load-bearing first, assigned by reading each title against B.3.1.
* `band` — A/B/C/D, defined below.
* `why_wanted_for_E1` — **the E1 question this paper answers**, in a sentence.
* `why_unavailable_detail` and `redistributable_if_supplied` — the licence consequence, spelled
  out per row rather than left implicit in a four-value enum.

`compute_priority` was **not** modified and nothing was written back to `manual_download_queue`.
The rank here is a curation proposal living in `docs/`, which is where a judgement the owner has
not ratified belongs.

---

## 3. The ranking rule

The brief is *"a paper that would actually change what E1 can say ranks above one that merely
matches the query."* B.3.1, as amended 2026-09-20, says what E1 is for: the **counterfactual
layer** — the C2 auxotrophy, the growth defect, the redox consequences of removing the principal
NADH sink, the compensating `GPD1`/`GPD2` glycerol branch, the evolved suppressors, and whatever
is needed to read the Gevo/Butamax-lineage literature, essentially all of which is Pdc-attenuated.

Four bands:

| band | what it means | n |
|---|---|---|
| **A** (ranks 1–12) | Would change what E1 can say. A Pdc-minus or Pdc-attenuated strain with its cost measured, or the branch-point partition measured directly. | **12** |
| **B** (13–25) | Needed to *read* the Pdc literature or to design attenuation rather than deletion: the isozyme set, autoregulation, `PDC2`, the `PDC1` UAS, dynamic control. B.3.1 admits promoter-replacement and dynamic-control strategies by name. | **13** |
| **C** (26–41) | Pdc genetics in another organism, or adjacent physiology. Buy only if a band-A item is unobtainable. | **16** |
| **D** (42–52) | Matched the E1 query and does not answer an E1 question. **Named so the decision not to buy them is on the record** rather than an oversight — one of them (rank 52) is a *Ustilago maydis* cell-polarity paper with no fermentation content at all. | **11** |

Bands are a reading of titles, journals and years against B.3.1. **No full text was consulted,
because by definition none is available** — that is the whole problem. So every `why_wanted_for_E1`
string is a prediction about a paper nobody here has read, and the bands should be treated as a
purchase order, not as a finding. Where a title is ambiguous the item was ranked down, not up.

---

## 4. The top of the list, with the reasoning stated

Full 52 in `E1_worklist.tsv`. The first twelve are band A:

| # | year | DOI | why E1 wants it | unavailable because |
|---|---|---|---|---|
| 1 | 2004 | `10.1128/AEM.70.1.159-166.2004` | *Directed evolution of pyruvate decarboxylase-negative S. cerevisiae, yielding a C2-independent, glucose-tolerant, and pyruvate-hyperproducing yeast.* **This is the paper B.3.1 is describing when it writes "the glucose-tolerance evolution that makes Pdc-minus strains usable ⚠".** It is the one item on this list whose absence is a hole in the criterion's own definition. | no PDF found |
| 2 | 1999 | `10.1111/j.1574-6968.1999.tb13551.x` | *Growth requirements of pyruvate-decarboxylase-negative S. cerevisiae.* Puts the number on the C2 auxotrophy — how much acetate a Pdc-negative cell has to be fed to grow at all. | paywalled |
| 3 | 2019 | `10.1016/j.jbiotec.2019.08.009` | `GPD1`/`GPD2` deletion **inside a Pdc-deficient background** — B.3.1's compensating glycerol branch, measured in the chassis where it is load-bearing. | paywalled |
| 4 | 2004 | `10.1128/AEM.70.5.2898-2905.2004` | A **negative** result: homolactic fermentation cannot sustain anaerobic growth. A failed substitution for the NADH sink bounds its cost harder than a successful one does. | no PDF found |
| 5 | 1999 | `10.1074/jbc.274.30.21044` | The mitochondrial pyruvate dehydrogenase bypass — the mechanism behind the C2 auxotrophy. | **licence forbids** |
| 6 | 2000 | `10.1128/AEM.66.8.3151-3159.2000` | PDH-bypass engineering with `ALD6` (cytosolic) and `ALD4` (matrix) apportioned. The only queue item that also reads across to E5, since Ald4 is one of the matrix NADPH routes B.3.5 names. | no PDF found |
| 7 | 2017 | `10.1002/bit.26048` | A `pdc1 pdc5` deletion background with an efficient LDH dropped into it — the shape of the Pdc-attenuated literature E1 exists to let us read. | paywalled |
| 8 | 2022 | `10.1080/10826068.2021.1910958` | A straight cost ledger: `pdc1`/`pdc5` knockout against parent, metabolite by metabolite, two haploid backgrounds. | paywalled |
| 9 | 2023 | `10.1002/biot.202200535` | Measures how flux at pyruvate **partitions** between lactate and ethanol as a function of glucose assimilation rate — the competition itself, rather than one side of it deleted. | **licence forbids** |
| 10 | 2019 | `10.1002/biot.201900013` | Transcriptome **and** flux profiling of Crabtree-negative S. cerevisiae. The only item that would serve both E1 and B.3.4's reprocessed-transcriptome slot for the *pdc*-minus background. | **licence forbids** |
| 11 | 2018 | `10.1016/j.cell.2018.07.013` | Alcoholic fermentation shut down wholesale, carbon redirected to lipid. The most complete available statement of what a cell does when the ethanol sink is removed. | **licence forbids** |
| 12 | 2006 | `10.1271/bbb.70.1148` | PDC knockout with lactate as the replacement sink, growth cost reported. Overlaps 7 and 9; buy if those fail. | **licence forbids** |

**Note the distribution.** Five of the top twelve are licence-forbidden, which is the worst
possible overlap: the band-A items are concentrated in exactly the category that cannot be stored
redistributably. That is section 6.

---

## 5. What is *not* worth buying, and why that is worth writing down

Band D is eleven papers that the E1 sub-query retrieved and that do not answer an E1 question.
They are listed in the TSV with the reason, not silently dropped, because PLAN.md H.3's rule is
that an excluded paper is a decision rather than an absence, and because a future change of mind
needs to be able to ask what was skipped.

The pattern in them is one the owner may want to act on: the E1 sub-query is
`(PDC1|PDC5|PDC6|"pyruvate decarboxylase") AND (deletion|knockout|...)`, and **"pyruvate
decarboxylase" appears in the abstract of any paper that engineers the Ehrlich route or
L-phenylacetylcarbinol, because Pdc catalyses the reaction they want** — the opposite of E1's
interest. Ranks 42, 46 and 49 are all of that kind. The query is doing what it was written to do;
the term is simply ambiguous between "the sink I am removing" and "the enzyme I am using".

---

## 6. The 14 licence-forbidden papers — a different kind of ask

**These are a separate request and must not be mixed with the other 38.** A file supplied for one
of these would be stored with `redistributable = false`: readable in-house, quotable into an
admission with offsets, and **not** redistributable with the atlas. `manual_queue.ingest_directory`
already stores any owner-supplied file as `oa_status='closed'`, `resolved_via='none'`, on the
stated principle that *"a file the owner drops in came from their own access, not a confirmed open
licence, and must never be treated as one just because a curator supplied it."* These 14 are the
rows where that is not a precaution but a known fact.

Sorted by rank (i.e. by how much E1 wants them):

| # | year | DOI | journal | what it gives E1 |
|---|---|---|---|---|
| 5 | 1999 | `10.1074/jbc.274.30.21044` | J. Biol. Chem. | The mitochondrial PDH bypass — the mechanism under the C2 auxotrophy |
| 9 | 2023 | `10.1002/biot.202200535` | Biotechnol. J. | The pyruvate branch-point partition, measured against glucose assimilation rate |
| 10 | 2019 | `10.1002/biot.201900013` | Biotechnol. J. | Transcriptome + flux of Crabtree-negative strains; also a B.3.4 transcriptome candidate |
| 11 | 2018 | `10.1016/j.cell.2018.07.013` | Cell | Fermentation-to-lipogenesis reprogramming; the fullest statement of life without the ethanol sink |
| 12 | 2006 | `10.1271/bbb.70.1148` | Biosci. Biotechnol. Biochem. | PDC knockout with a lactate replacement sink, growth cost reported |
| 18 | 1989 | `10.1007/BF00435452` | Curr. Genet. | A `PDC1` deletion behaves differently from the earlier point mutations — deletion vs. attenuation are not interchangeable |
| 19 | 1990 | `10.1111/j.1432-1033.1990.tb15442.x` | Eur. J. Biochem. | `PDC1`/`PDC5` autoregulation: attenuating one isozyme moves the others |
| 20 | 1999 | `10.1016/s0014-5793(99)00449-4` | FEBS Lett. | Thiamine repression as a second, orthogonal handle on Pdc level |
| 21 | 1999 | `10.1046/j.1432-1327.1999.00370.x` | Eur. J. Biochem. | Autoregulation needs the Pdc protein but not its catalysis — bears on a catalytically dead attenuation tool |
| 22 | 2013 | `10.1111/1567-1364.12052` | FEMS Yeast Res. | Pdc controlled post-translationally by Sit4p — the layer promoter engineering does not reach |
| 28 | 1999 | `10.1002/(SICI)1097-0061(19990330)15:5<361::AID-YEA378>3.0.CO;2-3` | Yeast | *K. lactis* `PDC1` regulation; right topic, wrong organism |
| 39 | 1993 | `10.1007/BF00310888` | Curr. Genet. | `ggs1`/`fdp1`/`byp1` suppression by hexokinase PII deletion — glucose-signalling background |
| 40 | 1993 | `10.1111/j.1432-1033.1993.tb17903.x` | Eur. J. Biochem. | Glucose-6-phosphate isomerase and glucose repression — background |
| 48 | 2012 | `10.1002/pmic.201100285` | Proteomics | `SCO1` deletion proteomics — respiratory assembly, off-criterion for E1 |

**If the owner wants to spend effort on only part of this section, it is ranks 5, 9, 10, 11 and
12.** Ranks 39, 40 and 48 are band C/D and would not change what E1 can say; they are listed for
completeness rather than as a request.

**A schema gap this exposes.** There is no `redistributable` column on `fulltext_asset`. The flag
this section keeps referring to is carried indirectly, by `oa_status='closed'` plus
`license IS NULL` plus `text_mining_allowed`. If the owner supplies these 14, the atlas will hold
14 assets whose non-redistributability is inferable but not asserted. That is a schema question,
it belongs to whoever owns `src/`, and it is flagged here rather than worked around.

---

## 7. What the owner is actually being asked

1. **Two free wins first.** Ranks 31 (`10.1002/bit.27576`) and 41
   (`10.1007/s00253-021-11394-9`) are `fetch_failed`, not refused. Re-run
   `fermdb literature acquire` for those two before opening a browser.
2. **The nine non-licence-forbidden band-A papers** (ranks 1, 2, 3, 4, 6, 7, 8 and, from band B,
   13 and 14). Rank 1 alone would close the largest single hole in the criterion.
3. **Separately, the five licence-forbidden band-A papers** (ranks 5, 9, 10, 11, 12), understanding
   that they arrive as `redistributable = false`.
4. **Nothing in bands C and D** unless a band-A item proves unobtainable, in which case the TSV
   names the substitute.

Even fully supplied, this does not spend E1's 25. PHASE2_STATUS.md §1 estimates ~6 admissible from
the 16 then readable; if the band-A twelve arrive and half of them hold up on reading, E1 lands
somewhere near 9–12 admitted against 25. **That residue is a finding, not a gap to pad** —
ETHANOL_REFERENCE_SLOTS.md's rule applies unchanged.
