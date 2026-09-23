/**
 * The typed client for the read-only API.
 *
 * The one type that matters more than the rest is `Value`. The server omits the `value` key
 * entirely on an absence rather than sending `null`, so the union below is discriminated by
 * whether `value` is present:
 *
 *     { display: "not recorded", absent: "not_recorded", absent_because: "..." }
 *     { display: "2.09", value: 2.09, zone: "R", zone_display: "reported" }
 *
 * Typing it as `value?: T` would let `v.value ?? 0` compile, which is exactly the silent bug
 * the server's shape was designed to prevent. So `isKnown()` is the only way in, and every
 * renderer goes through it.
 */

export type Zone = "R" | "H" | "I";
export type AbsenceKind = "not_recorded" | "not_applicable" | "unknown";

export interface KnownValue<T> {
  display: string;
  value: T;
  zone?: Zone;
  zone_display?: string;
}

export interface AbsentValue {
  display: string;
  absent: AbsenceKind;
  absent_because: string;
  zone?: Zone;
  zone_display?: string;
}

export type Value<T> = KnownValue<T> | AbsentValue;

/**
 * The only supported way to read a `Value`. Narrows the union; never defaults an absence.
 *
 * Total by construction. Not every field the API returns is a wrapped `Value` — some are plain
 * strings — and `"value" in someString` throws a TypeError that takes down the whole page. A
 * type guard that crashes on the shape it is guarding against is not a guard, so the object
 * check comes first and anything else is simply "not a known Value".
 */
export function isKnown<T>(v: Value<T> | null | undefined): v is KnownValue<T> {
  return (
    typeof v === "object" &&
    v !== null &&
    "value" in v &&
    (v as KnownValue<T>).value !== undefined
  );
}

/** The value, or `undefined` — for a caller that has already decided what absence means. */
export function valueOf<T>(v: Value<T> | null | undefined): T | undefined {
  return isKnown(v) ? v.value : undefined;
}

export interface Quantity {
  display: string;
  reported: Value<number>;
  unit_reported: Value<string>;
  si: Value<number>;
  unit_si: Value<string>;
  is_below_lod: boolean;
  is_upper_bound: boolean;
}

export interface Page<T> {
  rows: T[];
  count: number;
  truncated: boolean;
  limit?: number;
  offset?: number;
  note?: string;
}

export interface Health {
  ok: boolean;
  atlas: string;
  exists: boolean;
  size_bytes: number | null;
  writable_endpoints: number;
}

export interface EntityCoverage {
  label: string;
  count: number;
  pending: number;
  state: string;
  [key: string]: unknown;
}

export interface Coverage {
  entities: EntityCoverage[];
  pending_total: number;
  pending_by_kind: Record<string, number>;
  [key: string]: unknown;
}

export interface PageReadiness {
  page: string;
  renderable: boolean;
  note: string;
}

export interface FunnelStage {
  key: string;
  label: string;
  count: number;
  note: string;
  remedy?: string;
}

export interface LiteratureOverview {
  publications: number;
  screened: number;
  stages: FunnelStage[];
  by_family: Record<string, number>;
  by_triage_state: Record<string, number>;
  by_decision: Record<string, number>;
  by_decider_kind: Record<string, number>;
  by_source: { source: string; count: number }[];
  by_year: { year: number; count: number }[];
  acquisition: {
    readable: number;
    by_storage_state: Record<string, number>;
    manual_queue: number;
    fetch_errors: number;
    note: string;
  };
  search_runs: number;
  decider_note: string;
}

export interface PublicationRow {
  id: string;
  title: string | null;
  year: number | null;
  journal: string | null;
  doi: string | null;
}

export interface GenomeOverview {
  references: GenomeReference[];
  assets: GenomeReference[];
  encoding_genomes: {
    id: string;
    genetic_code_table: number;
    table_name: Value<string>;
    ribosome: Value<string>;
    compartments: string[];
  }[];
  compartments: {
    id: string;
    import_machinery: Value<string>;
    encoding_genomes: string[];
    is_dual_coded: boolean;
    ph_estimate: Value<string>;
    redox_estimate: Value<string>;
    warning?: string;
  }[];
  dual_coded_compartments: string[];
  mtdna_loci: {
    id: string;
    locus: string;
    encodes: Value<string>;
    activators: Value<string>;
    rescue_available: Value<string>;
    respiration_retained_if_used: boolean | null;
    displaced_if_used: Value<string>;
  }[];
  organisms: { id: string; name: string; ncbi_taxid: number | null; rank: string | null }[];
  strains_by_class: Record<string, number>;
}

export interface GenomeReference {
  id: string;
  kind: string;
  organism: Value<string>;
  accession: Value<string>;
  encoding_genome: Value<string>;
  size_bytes: number | null;
  checksum: Value<string>;
  translation_verified: boolean | null;
}

export interface StudyRead {
  study_accession: string;
  dataset_id: Value<string>;
  bioproject: Value<string>;
  organism: Value<string>;
  title: Value<string>;
  runs: number;
  expression_runs: number;
  downloaded: number;
  excluded: number;
  relevance_uncertain: number;
  strain_matched: number;
  by_strategy: Record<string, number>;
  usable_note: string;
}

export interface TranscriptOverview {
  datasets: number;
  runs: number;
  expression_runs: number;
  samples: number;
  samples_with_context: number;
  samples_without_context: number;
  context_note: string;
  studies: StudyRead[];
  by_strategy: Record<string, number>;
  by_acquisition_status: Record<string, number>;
  by_reference_match: Record<string, number>;
  by_repository: Record<string, number>;
  analyses: Record<string, number>;
}

export interface NetworkOverview {
  reactions: number;
  metabolites: number;
  reaction_genes: number;
  pathways: number;
  routes: number;
  viable_routes: number;
  routes_by_strategy: Record<string, number>;
  routes_by_balance: Record<string, number>;
  steps_by_compartment: Record<string, number>;
  steps_by_encoding_genome: Record<string, number>;
  parts_by_role: Record<string, number>;
  gaps_by_kind: Record<string, number>;
  unscored_axes: string[];
  headline: string;
  note: string;
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "reaction" | "metabolite";
  compartment: string | null;
  is_cofactor: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  role: string;
  coefficient: number | null;
}

export interface ReactionGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
  compartments: string[];
  competing_reactions: string[];
  note: string;
}

export interface RouteRow {
  id: string;
  cofactor_strategy: string | null;
  balance_status: string | null;
  score_balance: number | null;
  score_evidence: number | null;
  score_feasibility: number | null;
  score_transport: number | null;
  score_toxicity: number | null;
}

export interface DataOverview {
  measurements: number;
  experiments: number;
  strains: number;
  products: number;
  condition_contexts: number;
  by_quantity_kind: Record<string, number>;
  uncontrolled_kinds: number;
  singleton_kinds: number;
  quantity_kind_note: string;
  by_unit: Record<string, number>;
  unit_note: string;
  by_product: Record<string, number>;
  measurements_with_sample: number;
  measurements_with_publication: number;
  join_note: string;
  quality_flags: Record<string, number>;
  quality_severity: Record<string, number>;
  products_by_tier: Record<string, number>;
}

export interface MeasurementRow {
  id: string;
  quantity_kind: string;
  is_controlled_kind: boolean;
  quantity: Quantity;
  product_id: Value<string>;
  strain_id: Value<string>;
  publication_id: Value<string>;
  sample_id: Value<string>;
  basis: Value<string>;
  derived_by: Value<string>;
  assay_method: Value<string>;
  source_locator: Value<string>;
  flags: { kind: string; severity: string; rationale: string | null; status: string }[];
  comparability_warnings: string[];
}

export interface SearchGroup {
  kind: string;
  label: string;
  rows: Record<string, unknown>[];
  count: number;
  truncated: boolean;
}

export interface SearchHits {
  term: string;
  total: number;
  groups: SearchGroup[];
  empty_kinds: string[];
  technique: string;
  recall_caveat: string;
}

/**
 * The gene browser's payloads.
 *
 * Note what is and is not a `Value` here. `annotation_count` is a plain number because a count
 * is always known — zero annotations is a fact, not an absence. Everything the source may not
 * have recorded, including the coordinates, is a `Value`, so a gene with no `start` renders as
 * "not recorded" rather than as a gene at position 0.
 */
export interface GeneBrowserRow {
  id: string;
  display_name: string;
  systematic_name: Value<string>;
  standard_name: Value<string>;
  locus_tag: Value<string>;
  description: Value<string>;
  assembly_accession: Value<string>;
  seqid: Value<string>;
  chromosome: Value<string>;
  start: Value<number>;
  end: Value<number>;
  length: Value<number>;
  strand: Value<string>;
  biotype: Value<string>;
  gene_group_id: Value<string>;
  location: Value<string>;
  annotation_count: number;
}

/**
 * A page of genes, and the size of the answer it was cut from.
 *
 * `count` is this page. `total_matching` is the match. A header that renders `count` says
 * "50 genes" when it means "the first 50 of 4,812", and there is no way for a reader to tell.
 */
export interface GeneBrowserPage extends Page<GeneBrowserRow> {
  total_matching: number;
  has_more: boolean;
  ordered_by: string;
  orderings: string[];
  filters: Record<string, unknown>;
  searched_columns: string[];
  technique: string;
  /** Filters the live schema could not serve, each with the migration that would unblock it. */
  ignored_filters?: Record<string, string>;
  missing_columns?: Record<string, string>;
}

export interface GeneFacetValue {
  key: string;
  label: string;
  count: number;
}

/** A facet, or a stated reason there is no facet. An empty list renders those identically. */
export interface GeneFacet {
  key: string;
  label: string;
  available: boolean;
  values: GeneFacetValue[];
  blocked_reason?: string;
}

export interface GeneFacets {
  facets: GeneFacet[];
  /** Atlas-wide, deliberately NOT narrowed: they are the denominator a match is compared against. */
  totals: Record<string, number>;
  missing_columns: Record<string, string>;
  narrowed_by: Record<string, unknown>;
  counting: string;
}

export interface KaryotypeTrack {
  seqid: string;
  label: string;
  ordinal: number;
  kind: string;
  length: number;
  /** False when the length is only a lower bound from the genes seen on the sequence. */
  length_is_reference: boolean;
  gene_count: number;
  bins: number[];
  max_bin: number;
}

export interface KaryotypeRead {
  available: boolean;
  bin_width: number;
  tracks: KaryotypeTrack[];
  unplaced_genes: number;
  truncated: boolean;
  reference_assembly: string;
  blocked_reason?: string;
}

export interface GenePosition {
  gene_id: string;
  seqid: Value<string>;
  chromosome: Value<string>;
  sequence_length: Value<number>;
  start: Value<number>;
  end: Value<number>;
  length: Value<number>;
  strand: Value<string>;
  biotype: Value<string>;
  locus_tag: Value<string>;
  description: Value<string>;
  location: Value<string>;
  neighbours: GeneBrowserRow[];
  neighbourhood_bases: number;
  missing_columns: Record<string, string>;
}

export interface GeneBrowserParams {
  /** Index signature so these compose with `qs()`, which takes a plain bag of scalars. */
  [key: string]: string | number | boolean | undefined;
  q?: string;
  assembly?: string;
  seqid?: string;
  biotype?: string;
  strand?: string;
  has_coordinates?: boolean;
  annotated_by?: string;
  order_by?: string;
  limit?: number;
  offset?: number;
}

/* ------------------------------------------------------------------ the four entity pages
 *
 * The shapes below mirror `fermdb.query.{strains,experiments,products,compare}`. Two of them
 * carry a field with no visual equivalent anywhere else in this client and both are load-bearing:
 *
 * - `ComparabilityClass.status` is three-valued, not a boolean. "classified", "provisional" and
 *   "unclassified" are three different licences to compare, and collapsing them to
 *   `is_classified` would let a provisional class -- one whose key is blind to a facet that has
 *   no column -- pass as a real one.
 * - `Comparison.verdict` is likewise three-valued, and `refuse` is a successful answer with a
 *   200 beside it. PLAN.md I.2: refusal is the feature.
 */

export interface ContextFacet {
  facet: string;
  label: string;
  value: Value<string | number>;
  as_reported: Value<string>;
  unit?: string;
  is_class_defining: boolean;
}

export type ClassStatus = "classified" | "provisional" | "unclassified";

export interface ComparabilityClass {
  key: string;
  label: string;
  status: ClassStatus;
  is_classified: boolean;
  context_id: Value<string>;
  facets: ContextFacet[];
  blocked_by: string[];
  blind_to: string[];
  definition_source: string;
}

export interface ConditionContext {
  id: string;
  zone: Value<string>;
  confidence: Value<string>;
  completeness_score: Value<number>;
  facets: ContextFacet[];
  extra_facets: ContextFacet[];
  recorded: number;
  total_facets: number;
  /** Keyed by absence kind. Never summed: the three are not one number. */
  absent_by_kind: Record<string, number>;
  unavailable_class_facets: Record<string, string>;
  comparability_class: ComparabilityClass;
}

export interface StrainRow {
  id: string;
  canonical_name: string;
  organism_id: Value<string>;
  organism_name: Value<string>;
  strain_class: Value<string>;
  confidence: Value<string>;
  zone: Value<string>;
  measurements: number;
  modifications: number;
  samples: number;
  has_genotype: boolean;
  has_lineage: boolean;
}

export interface StrainListPage {
  rows: StrainRow[];
  count: number;
  truncated: boolean;
  limit?: number;
  offset?: number;
  /** Atlas-wide, deliberately NOT narrowed by the filters: it is the denominator. */
  by_class: Record<string, number>;
  total: number;
}

export interface Lineage {
  parents: Record<string, unknown>[];
  children: Record<string, unknown>[];
  is_recorded: boolean;
  rows_in_atlas: number;
  note: string;
}

export interface Modification {
  id: string;
  type: string;
  target_locus: Value<string>;
  target_gene_group_id: Value<string>;
  source_organism_id: Value<string>;
  details: Value<string>;
  publication_id: Value<string>;
  zone: Value<string>;
  confidence: Value<string>;
  subtype: Record<string, unknown>;
}

export interface PhenotypeGroup {
  class: ComparabilityClass;
  measurements: MeasurementRow[];
  count: number;
  units: string[];
  is_rankable: boolean;
}

export interface StrainDetail {
  id: string;
  canonical_name: string;
  organism_id: Value<string>;
  organism_name: Value<string>;
  strain_class: Value<string>;
  zone: Value<string>;
  evidence: Value<string>;
  confidence: Value<string>;
  aliases: { alias: string; source: string; zone: string; confidence: string }[];
  genotype: {
    id: string;
    as_reported: string;
    parsed: Record<string, unknown> | null;
    zone: string;
    confidence: string;
  }[];
  lineage: Lineage;
  modifications: Modification[];
  phenotype: PhenotypeGroup[];
  phenotype_truncated: boolean;
  /** Raw `chassis_profile` columns: the number is present only where the state says so. */
  tolerance: {
    id: string;
    name_as_reported: string;
    isobutanol_tolerance_g_l: number | null;
    isobutanol_tolerance_state: string | null;
    tolerance_endpoint: string | null;
    is_selected: number;
  }[];
  tolerance_note: string;
  samples: Record<string, unknown>[];
  transcriptome_note: string;
  publications: string[];
}

export interface ExperimentRow {
  id: string;
  publication_id: Value<string>;
  objective: Value<string>;
  design_type: Value<string>;
  zone: Value<string>;
  confidence: Value<string>;
  samples: number;
  samples_with_context: number;
  measurements: number;
}

export interface ExperimentDetail {
  id: string;
  publication_id: Value<string>;
  publication_title: Value<string>;
  objective: Value<string>;
  design_type: Value<string>;
  zone: Value<string>;
  evidence: Value<string>;
  confidence: Value<string>;
  samples: {
    id: string;
    strain_id: string | null;
    strain_name: string | null;
    dataset_id: string | null;
    condition_context_id: string | null;
    time_h: number | null;
    growth_phase: string | null;
  }[];
  samples_with_context: number;
  contexts: ConditionContext[];
  context_note: string;
  datasets: Record<string, unknown>[];
  analyses: Record<string, unknown>[];
  measurements: MeasurementRow[];
  measurements_truncated: boolean;
  measurement_note: string;
  quality_flags: { target_id: string; kind: string; severity: string; rationale: string | null }[];
}

export interface ProductRow {
  id: string;
  name: string;
  tier: Value<string>;
  canonical_unit: Value<string>;
  measurements: number;
  strains: number;
  configurations: number;
  theoretical_yields: number;
}

export interface ClassFacetedMeasurements {
  class: ComparabilityClass;
  measurements: MeasurementRow[];
  count: number;
  units: string[];
  kinds: string[];
  is_rankable: boolean;
  /** Why no best is named in this class. Null only when one is. */
  refusal_reason: string | null;
  best: Record<string, MeasurementRow>;
}

export interface ProductDetail {
  id: string;
  name: string;
  tier: Value<string>;
  mw_g_mol: Value<number>;
  formula: Value<string>;
  inchikey: Value<string>;
  chebi_id: Value<string>;
  carbon_number: Value<number>;
  canonical_unit: Value<string>;
  zone: Value<string>;
  confidence: Value<string>;
  theoretical_yields: {
    substrate: string;
    g_per_g: Value<number>;
    mol_per_mol: Value<number>;
    stoichiometry: Value<string>;
  }[];
  pathways: { id: string; name: string; linked_directly: boolean; reactions: number }[];
  pathway_note: string;
  configurations: {
    id: string;
    name: string;
    pathway_id: string | null;
    compartment_strategy_id: string | null;
    host_strain_id: string | null;
    host_strain_name: string | null;
    description: string | null;
  }[];
  classes: ClassFacetedMeasurements[];
  measurements_truncated: boolean;
  tolerance: {
    id: string;
    strain_id: string | null;
    name_as_reported: string;
    tolerance: Value<number>;
    tolerance_endpoint: Value<string>;
    is_selected: boolean;
  }[];
  tolerance_note: string;
  strains: { id: string; canonical_name: string; strain_class: string | null }[];
  leaderboard_refusal: string;
}

export interface FacetDifference {
  facet: string;
  label: string;
  values: string[];
  differs: boolean;
  within_tolerance: boolean;
  is_class_defining: boolean;
  tolerance?: string;
}

export interface CompareSubject {
  kind: string;
  id: string;
  label: string;
  attributes: { label: string; value: Value<string> }[];
  classes: ComparabilityClass[];
  context: ConditionContext | null;
  context_note: string;
  measurements: MeasurementRow[];
}

export type Verdict = "comparable" | "warn" | "refuse";

export interface Metric {
  quantity_kind: string;
  unit: string;
  /** Positional against `Comparison.subjects`; a null is "this subject has no such number". */
  values: (MeasurementRow | null)[];
  is_controlled_kind: boolean;
}

export interface Comparison {
  kind: string;
  requested: string[];
  subjects: CompareSubject[];
  missing: string[];
  verdict: Verdict;
  reason: string;
  warnings: string[];
  differences: FacetDifference[];
  differing_facets: string[];
  metrics: Metric[];
}

export interface CompareCandidate {
  id: string;
  label: string;
  detail: Value<string>;
  weight: number;
}

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: string,
  ) {
    super(`${status}: ${detail}`);
    this.name = "ApiError";
  }
}

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`/api${path}`, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    // The server's `detail` is written for a person; surfacing it beats a bare status code.
    let detail = response.statusText;
    try {
      const body = (await response.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* a non-JSON error body is still an error; keep the status text */
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") search.set(key, String(value));
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}

export const api = {
  health: () => get<Health>("/health"),
  coverage: () => get<Coverage>("/atlas/coverage"),
  pages: () => get<PageReadiness[]>("/atlas/pages"),
  search: (q: string, limit = 10) => get<SearchHits>(`/search${qs({ q, limit })}`),

  literatureOverview: () => get<LiteratureOverview>("/literature/overview"),
  literatureFamilies: () => get<string[]>("/literature/families"),
  publications: (params: {
    q?: string;
    year?: number;
    family?: string;
    triage_state?: string;
    readable_only?: boolean;
    limit?: number;
    offset?: number;
  }) => get<Page<PublicationRow>>(`/literature/publications${qs(params)}`),
  publication: (id: string) =>
    get<Record<string, unknown>>(`/literature/publications/${encodeURIComponent(id)}`),

  genomes: () => get<GenomeOverview>("/genomes/overview"),

  genes: (limit = 200) => get<{ id: string; name: string }[]>(`/annotations/genes${qs({ limit })}`),
  gene: (id: string) => get<Record<string, unknown>>(`/annotations/genes/${encodeURIComponent(id)}`),

  // The gene browser. `/genes/{id}` returns the same payload `/annotations/genes/{id}` does,
  // including `absent_sections`, with a `position` block added — so the gene page gains
  // coordinates without losing the statement about what the atlas cannot show.
  geneBrowser: (params: GeneBrowserParams) => get<GeneBrowserPage>(`/genes${qs(params)}`),
  geneFacets: (params: Omit<GeneBrowserParams, "order_by" | "limit" | "offset"> = {}) =>
    get<GeneFacets>(`/genes/facets${qs(params)}`),
  karyotype: (params: Omit<GeneBrowserParams, "seqid" | "order_by" | "limit" | "offset">) =>
    get<KaryotypeRead>(`/genes/karyotype${qs(params)}`),
  geneDetail: (id: string) =>
    get<Record<string, unknown> & { position: GenePosition | null }>(
      `/genes/${encodeURIComponent(id)}`,
    ),

  transcripts: () => get<TranscriptOverview>("/transcripts/overview"),
  runs: (params: { study?: string; strategy?: string; limit?: number; offset?: number }) =>
    get<Page<Record<string, unknown>>>(`/transcripts/runs${qs(params)}`),

  networks: () => get<NetworkOverview>("/networks/overview"),
  graph: (pathway?: string) => get<ReactionGraph>(`/networks/graph${qs({ pathway })}`),
  routes: (params: {
    cofactor_strategy?: string;
    balance_status?: string;
    order_by?: string;
    limit?: number;
    offset?: number;
  }) => get<Page<RouteRow> & { ordered_by: string }>(`/networks/routes${qs(params)}`),
  route: (id: string) => get<Record<string, unknown>>(`/networks/routes/${encodeURIComponent(id)}`),
  pathways: () => get<{ id: string; name: string }[]>("/pathways"),
  pathway: (id: string) => get<Record<string, unknown>>(`/pathways/${encodeURIComponent(id)}`),
  pathwayGaps: () => get<Record<string, string[]>>("/pathways/gaps"),

  dataOverview: () => get<DataOverview>("/data/overview"),
  measurements: (params: {
    product_id?: string;
    strain_id?: string;
    quantity_kind?: string;
    publication_id?: string;
    limit?: number;
    offset?: number;
  }) => get<Page<MeasurementRow>>(`/data/measurements${qs(params)}`),

  strains: (params: { q?: string; class?: string; limit?: number; offset?: number }) =>
    get<StrainListPage>(`/strains${qs(params)}`),
  strain: (id: string) => get<StrainDetail>(`/strains/${encodeURIComponent(id)}`),

  experiments: (params: { q?: string; limit?: number; offset?: number }) =>
    get<Page<ExperimentRow>>(`/experiments${qs(params)}`),
  experiment: (id: string) => get<ExperimentDetail>(`/experiments/${encodeURIComponent(id)}`),

  products: () => get<ProductRow[]>("/products"),
  product: (id: string) => get<ProductDetail>(`/products/${encodeURIComponent(id)}`),

  // `id` repeats rather than joining on a separator, because an atlas identifier contains
  // colons and any separator chosen today is one an identifier may carry tomorrow.
  compare: (kind: string, ids: string[]) => {
    const params = new URLSearchParams();
    params.set("kind", kind);
    for (const id of ids) params.append("id", id);
    return get<Comparison>(`/compare?${params.toString()}`);
  },
  compareCandidates: (kind: string) =>
    get<CompareCandidate[]>(`/compare/candidates${qs({ kind })}`),

  assertions: () => get<Record<string, unknown>>("/evidence/assertions"),
  curationQueue: (limit = 10) => get<Record<string, unknown>[]>(`/curation/queue${qs({ limit })}`),
};
