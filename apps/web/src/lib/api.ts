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

  assertions: () => get<Record<string, unknown>>("/evidence/assertions"),
  curationQueue: (limit = 10) => get<Record<string, unknown>[]>(`/curation/queue${qs({ limit })}`),
};
