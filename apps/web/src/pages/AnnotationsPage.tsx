/**
 * Annotations: a gene browser, and one gene in full.
 *
 * This page used to be 36 cards and a substring filter over the array the client had already
 * downloaded. That was honest at 36 genes and becomes a lie at 6,600: a client-side filter
 * narrows *what was sent*, which is only the same thing as narrowing what the atlas holds when
 * everything fits in one response. So search, facets, sorting and paging all happen in SQL, and
 * the page reports a `total_matching` that is a real count rather than the length of the array
 * in front of it. "50 genes" and "the first 50 of 4,812" are different sentences.
 *
 * Every filter lives in the URL. A chromosome, a biotype and a search term compose into a link
 * someone can send, and the back button undoes a facet click. Filter state held in `useState`
 * would look identical and do none of that.
 *
 * The gene payload still carries `absent_sections` — the P.2 sections this page cannot fill and
 * the reason for each — and it is rendered as prominently as the content. PLAN.md O.2 point 4:
 * absence is reported as absence. A gene page that quietly omitted its empty sections would look
 * complete; this one looks honestly partial, which is the more useful lie-free state.
 */

import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ArrowLeft, ChevronLeft, ChevronRight, MapPin, Search, X } from "lucide-react";

import { ChromosomeMap } from "@/components/ChromosomeMap";
import { Caveat, Field, ValueView } from "@/components/Value";
import {
  Cell,
  Empty,
  ErrorBox,
  Link,
  Loading,
  PageHeader,
  Panel,
  Row,
  Stat,
  StatGrid,
  Table,
} from "@/components/ui";
import {
  api,
  isKnown,
  type GeneBrowserRow,
  type GeneFacet,
  type GenePosition,
  type Value,
} from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

/** One screen of rows. Large enough to be worth paging, small enough to stay scannable. */
const PAGE_SIZE = 50;

/** Long enough that typing a gene name is one query, short enough to feel like filtering. */
const DEBOUNCE_MS = 250;

type AnnotationsRoute = Extract<Route, { name: "annotations" }>;

/** Which facet key drives which URL parameter. The API and the URL name two of them differently
 * (`annotated_by` / `source`), and the mapping lives here rather than being spelled out at four
 * call sites that can drift apart. */
const FACET_PARAM: Record<string, keyof AnnotationsRoute> = {
  seqid: "seqid",
  biotype: "biotype",
  assembly: "assembly",
  annotated_by: "source",
  strand: "strand",
};

interface Annotation {
  source: string;
  term_id: string;
  term_label: Value<string>;
  namespace: Value<string>;
  evidence_code: Value<string>;
}

interface ReactionRole {
  reaction_id: string;
  reaction_name: Value<string>;
  pathway_id: Value<string>;
  compartment_id?: Value<string>;
  [key: string]: unknown;
}

interface GeneDetail {
  id: string;
  systematic_name: Value<string>;
  standard_name: Value<string>;
  organism_id: Value<string>;
  assembly_accession: Value<string>;
  gene_group_id: Value<string>;
  gene_group_anchor: Value<string>;
  annotations: Annotation[];
  reactions: ReactionRole[];
  modifications: unknown[];
  absent_sections: Record<string, string>;
  counts: Record<string, number>;
  position: GenePosition | null;
}

// ------------------------------------------------------------------ the browser

export function AnnotationsPage({ route }: { route: AnnotationsRoute }) {
  const page = Math.max(1, route.page ?? 1);
  const offset = (page - 1) * PAGE_SIZE;

  // The box is local state so typing is not one history entry per keystroke; the URL catches up
  // once the typing stops, and `replace` keeps the back button meaning "the previous view".
  const [term, setTerm] = useState(route.q ?? "");
  useEffect(() => setTerm(route.q ?? ""), [route.q]);
  useEffect(() => {
    if ((route.q ?? "") === term) return;
    const timer = setTimeout(
      () => navigate({ ...route, q: term || undefined, page: undefined }, true),
      DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [term]);

  // Everything except the chromosome. The karyotype is how a chromosome gets chosen, so filtering
  // it by the chosen one would leave a single track and no way back to the others.
  const shared = {
    q: route.q,
    assembly: route.assembly,
    biotype: route.biotype,
    strand: route.strand,
    annotated_by: route.source,
  };

  // Facet counts are narrowed by the active filters, so "442" under Chromosome means "442 of the
  // genes you are currently looking at", not "442 in the atlas". An un-narrowed rail sitting
  // beside a narrowed karyotype is two different answers to the same question.
  const facets = useQuery({
    queryKey: ["gene-facets", shared, route.seqid],
    queryFn: () => api.geneFacets({ ...shared, seqid: route.seqid }),
    placeholderData: keepPreviousData,
  });

  const karyotype = useQuery({
    queryKey: ["karyotype", shared],
    queryFn: () => api.karyotype(shared),
    placeholderData: keepPreviousData,
  });

  const genes = useQuery({
    queryKey: ["gene-browser", shared, route.seqid, route.order, offset],
    queryFn: () =>
      api.geneBrowser({
        ...shared,
        seqid: route.seqid,
        order_by: route.order ?? "position",
        limit: PAGE_SIZE,
        offset,
      }),
    placeholderData: keepPreviousData,
  });

  if (facets.isLoading && !facets.data) return <Loading what="the gene index" />;
  if (facets.error) return <ErrorBox error={facets.error} />;
  const facetData = facets.data!;

  const setFilter = (key: keyof AnnotationsRoute, value: string | undefined) =>
    navigate({ ...route, [key]: value, page: undefined });

  const activeChips = Object.entries(FACET_PARAM)
    .map(([, param]) => [param, route[param]] as const)
    .filter(([, value]) => typeof value === "string" && value)
    .concat(route.q ? ([["q", route.q]] as const) : []);

  const totals = facetData.totals;
  const matching = genes.data?.total_matching;
  const pendingMigration = Object.keys(facetData.missing_columns ?? {});

  return (
    <div className="space-y-6">
      <PageHeader
        title="Genes"
        lede="Every gene the atlas holds, searchable by name, locus tag and description and
              filterable by chromosome, biotype, strand and annotation source. Annotations hang
              from the gene group rather than the gene row, which is what makes ADH2 and YMR303C
              the same thing when a paper says one and the atlas keys on the other."
      />

      <StatGrid>
        <Stat label="Genes" value={totals.genes ?? 0} hint="rows in the gene table" />
        <Stat
          label="Matching"
          value={matching ?? "…"}
          // Zero matches is not a success. Green on 0 would read as "filtered down nicely" when
          // what happened is that the filters exclude everything.
          tone={
            matching === 0
              ? "muted"
              : matching !== undefined && matching < (totals.genes ?? 0)
                ? "good"
                : "default"
          }
          hint={
            matching === undefined
              ? "counting"
              : matching === 0
                ? "nothing matches these filters"
                : matching === totals.genes
                  ? "no filter applied"
                  : `of ${(totals.genes ?? 0).toLocaleString()} — a count, not a page length`
          }
        />
        <Stat
          label="Located"
          value={totals.with_coordinates ?? 0}
          tone={(totals.without_coordinates ?? 0) > 0 ? "warn" : "good"}
          hint={
            (totals.without_coordinates ?? 0) > 0
              ? `${totals.without_coordinates} hold no start/end and cannot be drawn`
              : "every gene carries start and end"
          }
        />
        <Stat
          label="Annotated"
          value={totals.with_annotation ?? 0}
          tone={(totals.without_annotation ?? 0) > 0 ? "warn" : "good"}
          hint={`${(totals.without_annotation ?? 0).toLocaleString()} carry no functional term`}
        />
      </StatGrid>

      {pendingMigration.length > 0 && (
        <Caveat>
          This atlas predates the columns the browser filters on:{" "}
          <code className="text-amber-100">{pendingMigration.join(", ")}</code>. Those facets are
          shown as blocked rather than empty, because "the atlas has no tRNAs" and "the atlas cannot
          yet tell a tRNA from an ORF" are different claims. Run{" "}
          <code className="text-amber-100">fermdb db migrate</code> and the loader that backfills
          them.
        </Caveat>
      )}

      <Panel
        title="Chromosomes"
        subtitle={
          karyotype.data?.available
            ? "17 sequences of the S288C reference, to scale, shaded by gene density — click a track to filter"
            : "the reference karyotype, with nothing placed on it yet"
        }
        right={
          route.seqid && (
            <button
              onClick={() => setFilter("seqid", undefined)}
              className="text-[11px] text-zinc-500 hover:text-zinc-300"
            >
              show all chromosomes
            </button>
          )
        }
      >
        {karyotype.isLoading && !karyotype.data ? (
          <Loading what="the karyotype" />
        ) : karyotype.error ? (
          <ErrorBox error={karyotype.error} />
        ) : (
          <div className="space-y-3">
            <ChromosomeMap
              data={karyotype.data!}
              selected={route.seqid ? resolveSeqid(karyotype.data!, route.seqid) : undefined}
              onSelect={(seqid) => setFilter("seqid", seqid)}
            />
            {!karyotype.data!.available && (
              <Caveat>
                No gene carries a sequence accession yet, so all{" "}
                {karyotype.data!.unplaced_genes.toLocaleString()} of them are unplaced and every
                track is empty. {karyotype.data!.blocked_reason}
              </Caveat>
            )}
            {karyotype.data!.available && karyotype.data!.unplaced_genes > 0 && (
              <Caveat>
                {karyotype.data!.unplaced_genes.toLocaleString()} gene(s) are not on any track: they
                carry no sequence accession, or no coordinates, so there is nowhere on this figure
                to put them. They are still in the table below.
              </Caveat>
            )}
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-4">
        <div className="space-y-4 lg:col-span-1">
          <div className="relative">
            <Search className="pointer-events-none absolute left-2.5 top-2.5 h-3.5 w-3.5 text-zinc-600" />
            <input
              value={term}
              onChange={(event) => setTerm(event.target.value)}
              placeholder="ADH2, YMR303C, dehydrogenase…"
              className="w-full rounded border border-zinc-700 bg-zinc-950 py-1.5 pl-8 pr-7 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-sky-600 focus:outline-none"
            />
            {term && (
              <button
                onClick={() => setTerm("")}
                aria-label="clear search"
                className="absolute right-2 top-2 text-zinc-600 hover:text-zinc-300"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            )}
          </div>

          {genes.data && route.q && (
            <p className="text-[10px] leading-relaxed text-zinc-600">{genes.data.technique}.</p>
          )}

          {Object.keys(facetData.narrowed_by ?? {}).length > 0 && (
            <p className="text-[10px] leading-relaxed text-zinc-600">{facetData.counting}.</p>
          )}

          {facetData.facets.map((facet) => (
            <FacetPanel
              key={facet.key}
              facet={facet}
              active={route[FACET_PARAM[facet.key] ?? "q"] as string | undefined}
              onToggle={(value) => setFilter(FACET_PARAM[facet.key], value)}
            />
          ))}
        </div>

        <div className="space-y-4 lg:col-span-3">
          {activeChips.length > 0 && (
            <div className="flex flex-wrap items-center gap-1.5">
              <span className="text-[11px] text-zinc-600">filtered by</span>
              {activeChips.map(([param, value]) => (
                <button
                  key={param}
                  onClick={() =>
                    param === "q"
                      ? setTerm("")
                      : setFilter(param as keyof AnnotationsRoute, undefined)
                  }
                  className="inline-flex items-center gap-1 rounded-full border border-sky-800/60 bg-sky-500/10 px-2 py-0.5 text-[11px] text-sky-200 hover:border-sky-600"
                >
                  <span className="text-sky-500/70">{param}</span>
                  {String(value)}
                  <X className="h-3 w-3" />
                </button>
              ))}
              <button
                onClick={() => navigate({ name: "annotations" })}
                className="ml-1 text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                clear all
              </button>
            </div>
          )}

          <Panel
            title="Genes"
            subtitle={
              genes.data
                ? `${genes.data.count.toLocaleString()} shown of ${genes.data.total_matching.toLocaleString()} matching`
                : "reading"
            }
            right={
              genes.data && (
                <Pager
                  page={page}
                  pageSize={PAGE_SIZE}
                  total={genes.data.total_matching}
                  onGo={(next) => navigate({ ...route, page: next })}
                />
              )
            }
          >
            {genes.error ? (
              <ErrorBox error={genes.error} />
            ) : !genes.data ? (
              <Loading what="genes" />
            ) : genes.data.rows.length === 0 ? (
              <Empty>
                no gene matches this combination of filters — the atlas holds{" "}
                {(totals.genes ?? 0).toLocaleString()} genes in total
              </Empty>
            ) : (
              <GeneTable
                rows={genes.data.rows}
                order={genes.data.ordered_by}
                onOrder={(order) => navigate({ ...route, order, page: undefined })}
              />
            )}

            {genes.data?.ignored_filters && (
              <div className="mt-4 space-y-2">
                {Object.entries(genes.data.ignored_filters).map(([name, reason]) => (
                  <Caveat key={name}>
                    The <code className="text-amber-100">{name}</code> filter in this URL was not
                    applied: {reason}. The rows below are unfiltered by it, rather than filtered to
                    nothing.
                  </Caveat>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    </div>
  );
}

/** The URL may say `chrIV` where the karyotype is keyed by accession. Fold one onto the other. */
function resolveSeqid(data: { tracks: { seqid: string; label: string }[] }, wanted: string) {
  const folded = wanted.toLowerCase();
  return data.tracks.find(
    (t) => t.seqid.toLowerCase() === folded || t.label.toLowerCase() === folded,
  )?.seqid;
}

function FacetPanel({
  facet,
  active,
  onToggle,
}: {
  facet: GeneFacet;
  active: string | undefined;
  onToggle: (value: string | undefined) => void;
}) {
  // Chromosomes are 17 rows and everything else is a handful; a scroll box keeps the rail one
  // screen tall without hiding options behind a "show more" nobody clicks.
  return (
    <Panel title={facet.label} className="text-xs">
      {!facet.available ? (
        <p className="rounded border border-dashed border-amber-900/50 bg-amber-500/5 px-2.5 py-2 text-[11px] leading-relaxed text-amber-200/80">
          Blocked on a pending migration: {facet.blocked_reason}
        </p>
      ) : facet.values.length === 0 ? (
        <Empty>no values recorded</Empty>
      ) : (
        <ul className="max-h-64 space-y-0.5 overflow-y-auto pr-1">
          {facet.values.map((value) => {
            const on = active === value.key;
            return (
              <li key={value.key}>
                <button
                  onClick={() => onToggle(on ? undefined : value.key)}
                  className={`flex w-full items-center justify-between gap-2 rounded px-2 py-1 text-left text-[11px] ${
                    on
                      ? "bg-sky-500/15 text-sky-200 ring-1 ring-inset ring-sky-700/50"
                      : "text-zinc-300 hover:bg-zinc-800/60"
                  }`}
                >
                  <span className="truncate" title={value.label}>
                    {value.label}
                  </span>
                  <span className="shrink-0 font-mono tabular-nums text-zinc-500">
                    {value.count.toLocaleString()}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

/**
 * The results table.
 *
 * `Table` from the shared vocabulary takes plain strings for its head, and these headers are
 * buttons — so the header row is written out here and the body still uses the shared `Row`/`Cell`
 * so a gene row looks like every other row in the interface.
 */
function GeneTable({
  rows,
  order,
  onOrder,
}: {
  rows: GeneBrowserRow[];
  order: string;
  onOrder: (order: string) => void;
}) {
  const columns: [string, string | null, string][] = [
    ["Gene", "name", ""],
    ["Systematic", null, ""],
    ["Location", "position", ""],
    ["Strand", null, "text-center"],
    ["Length", "length", "text-right"],
    ["Biotype", null, ""],
    ["Terms", "annotations", "text-right"],
  ];

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-800">
            {columns.map(([label, key, align]) => (
              <th
                key={label}
                className={`whitespace-nowrap px-3 py-2 text-xs font-medium uppercase tracking-wide text-zinc-500 ${align || "text-left"}`}
              >
                {key ? (
                  <SortButton label={label} base={key} order={order} onOrder={onOrder} />
                ) : (
                  label
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((gene) => (
            <Row key={gene.id}>
              <Cell>
                <Link to={{ name: "gene", id: gene.id }}>{gene.display_name}</Link>
                {isKnown(gene.description) && (
                  <div
                    className="max-w-xs truncate text-[10px] text-zinc-600"
                    title={gene.description.value}
                  >
                    {gene.description.value}
                  </div>
                )}
              </Cell>
              <Cell className="font-mono text-[11px]">
                <ValueView v={gene.systematic_name} mono showZone={false} />
              </Cell>
              <Cell className="whitespace-nowrap font-mono text-[11px]">
                <ValueView v={gene.location} mono showZone={false} />
              </Cell>
              <Cell className="text-center font-mono text-[11px]">
                <ValueView v={gene.strand} mono showZone={false} />
              </Cell>
              <Cell className="text-right font-mono text-[11px] tabular-nums">
                {isKnown(gene.length) ? (
                  `${gene.length.value.toLocaleString()} bp`
                ) : (
                  <ValueView v={gene.length} mono showZone={false} />
                )}
              </Cell>
              <Cell className="text-[11px]">
                <ValueView v={gene.biotype} showZone={false} />
              </Cell>
              <Cell className="text-right font-mono text-[11px] tabular-nums">
                <span className={gene.annotation_count === 0 ? "text-zinc-700" : "text-zinc-300"}>
                  {gene.annotation_count}
                </span>
              </Cell>
            </Row>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** A column header that toggles between the ascending and descending form of its ordering. */
function SortButton({
  label,
  base,
  order,
  onOrder,
}: {
  label: string;
  base: string;
  order: string;
  onOrder: (order: string) => void;
}) {
  // `length` and `annotations` are descending-first (biggest is the interesting end); `name` and
  // `position` are ascending-first. The alternate form is whichever one is not current.
  const descendingFirst = base === "length" || base === "annotations";
  const primary = base;
  const secondary = descendingFirst ? `${base}_asc` : `${base}_desc`;
  const active = order === primary || order === secondary;
  const next = order === primary ? secondary : primary;
  const arrow = !active
    ? ""
    : order.endsWith("_asc") || (!descendingFirst && order === primary)
      ? "↑"
      : "↓";

  return (
    <button
      onClick={() => onOrder(next)}
      className={`inline-flex items-center gap-1 uppercase tracking-wide hover:text-zinc-300 ${
        active ? "text-sky-300" : ""
      }`}
    >
      {label}
      <span className="w-2 font-mono">{arrow}</span>
    </button>
  );
}

function Pager({
  page,
  pageSize,
  total,
  onGo,
}: {
  page: number;
  pageSize: number;
  total: number;
  onGo: (page: number) => void;
}) {
  const last = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(page * pageSize, total);
  const button =
    "rounded border border-zinc-800 p-1 text-zinc-400 enabled:hover:border-zinc-600 enabled:hover:text-zinc-200 disabled:opacity-30";

  return (
    <div className="flex items-center gap-2 text-[11px] text-zinc-500">
      <span className="font-mono tabular-nums">
        {from.toLocaleString()}–{to.toLocaleString()} of {total.toLocaleString()}
      </span>
      <button className={button} disabled={page <= 1} onClick={() => onGo(page - 1)}>
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <span className="font-mono tabular-nums">
        {page} / {last}
      </span>
      <button className={button} disabled={page >= last} onClick={() => onGo(page + 1)}>
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

// ------------------------------------------------------------------ one gene

export function GenePage({ id }: { id: string }) {
  const gene = useQuery({
    queryKey: ["gene-detail", id],
    queryFn: () => api.geneDetail(id) as unknown as Promise<GeneDetail>,
  });

  if (gene.isLoading) return <Loading what="the gene" />;
  if (gene.error) return <ErrorBox error={gene.error} />;
  const data = gene.data as unknown as GeneDetail;
  const position = data.position;

  const name = isKnown(data.standard_name)
    ? data.standard_name.value
    : isKnown(data.systematic_name)
      ? data.systematic_name.value
      : data.id;

  const byNamespace = new Map<string, Annotation[]>();
  for (const annotation of data.annotations ?? []) {
    const key = isKnown(annotation.namespace) ? annotation.namespace.value : "other";
    byNamespace.set(key, [...(byNamespace.get(key) ?? []), annotation]);
  }

  return (
    <div className="space-y-6">
      <Link to={{ name: "annotations" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Genes
      </Link>

      <header>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-50">{name}</h1>
        <p className="mt-1 font-mono text-xs text-zinc-500">{data.id}</p>
        {position && isKnown(position.location) && (
          <p className="mt-2 font-mono text-xs text-zinc-400">
            <MapPin className="mr-1 inline h-3 w-3 text-zinc-600" />
            {position.location.value}
            {isKnown(position.strand) && (
              <span className="ml-2 text-zinc-500">strand {position.strand.value}</span>
            )}
            {isKnown(position.seqid) && (
              <Link
                to={{ name: "annotations", seqid: position.seqid.value }}
                className="ml-3 text-[11px]"
              >
                browse this chromosome →
              </Link>
            )}
          </p>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Identity" className="lg:col-span-1">
          <dl>
            <Field label="Standard name">
              <ValueView v={data.standard_name} />
            </Field>
            <Field label="Systematic name">
              <ValueView v={data.systematic_name} mono />
            </Field>
            {position && (
              <Field label="Locus tag">
                <ValueView v={position.locus_tag} mono />
              </Field>
            )}
            <Field label="Gene group">
              <ValueView v={data.gene_group_id} mono />
            </Field>
            <Field label="Anchor">
              <ValueView v={data.gene_group_anchor} mono />
            </Field>
            <Field label="Assembly">
              <ValueView v={data.assembly_accession} mono />
            </Field>
            <Field label="Organism">
              <ValueView v={data.organism_id} mono />
            </Field>
          </dl>
        </Panel>

        <Panel
          title="Position"
          subtitle="0-based half-open coordinates, as the assembly reports them"
          className="lg:col-span-2"
        >
          {!position ? (
            <Empty>no positional record for this gene</Empty>
          ) : (
            <>
              <dl className="grid gap-x-6 sm:grid-cols-2">
                <Field label="Sequence">
                  <ValueView v={position.seqid} mono />
                </Field>
                <Field label="Chromosome">
                  <ValueView v={position.chromosome} />
                </Field>
                <Field label="Start">
                  <ValueView v={position.start} mono />
                </Field>
                <Field label="End">
                  <ValueView v={position.end} mono />
                </Field>
                <Field label="Length">
                  <ValueView v={position.length} mono />
                </Field>
                <Field label="Strand">
                  <ValueView v={position.strand} mono />
                </Field>
                <Field label="Biotype">
                  <ValueView v={position.biotype} />
                </Field>
                <Field label="Description">
                  <ValueView v={position.description} />
                </Field>
              </dl>
              {Object.keys(position.missing_columns ?? {}).length > 0 && (
                <Caveat>
                  This atlas has not been migrated for{" "}
                  <code className="text-amber-100">
                    {Object.keys(position.missing_columns).join(", ")}
                  </code>
                  , so those fields read "not recorded" here because the column does not exist — not
                  because the source stayed silent about this gene.
                </Caveat>
              )}
            </>
          )}
        </Panel>
      </div>

      {position && position.neighbours.length > 0 && (
        <Panel
          title="Neighbourhood"
          subtitle={`genes within ${(position.neighbourhood_bases / 1000).toFixed(0)} kb either side, in coordinate order`}
        >
          <Table head={["Gene", "Location", "Strand", "Length", "Biotype", "Terms"]}>
            {position.neighbours.map((neighbour) => {
              const self = neighbour.id === position.gene_id;
              return (
                <Row key={neighbour.id}>
                  <Cell className={self ? "font-semibold text-sky-300" : ""}>
                    {self ? (
                      neighbour.display_name
                    ) : (
                      <Link to={{ name: "gene", id: neighbour.id }}>{neighbour.display_name}</Link>
                    )}
                  </Cell>
                  <Cell className="whitespace-nowrap font-mono text-[11px]">
                    <ValueView v={neighbour.location} mono showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-[11px]">
                    <ValueView v={neighbour.strand} mono showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-[11px] tabular-nums">
                    <ValueView v={neighbour.length} mono showZone={false} />
                  </Cell>
                  <Cell className="text-[11px]">
                    <ValueView v={neighbour.biotype} showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-[11px] tabular-nums text-zinc-400">
                    {neighbour.annotation_count}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        </Panel>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel
          title="Reactions"
          subtitle="where this gene acts, and in which compartment"
          className="lg:col-span-3"
        >
          {(data.reactions ?? []).length === 0 ? (
            <Empty>this gene is not attached to any curated reaction</Empty>
          ) : (
            <Table head={["Reaction", "Pathway", "Compartment"]}>
              {data.reactions.map((reaction) => (
                <Row key={reaction.reaction_id}>
                  <Cell className="text-xs">
                    <ValueView v={reaction.reaction_name} showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-[11px]">
                    {isKnown(reaction.pathway_id) ? (
                      <Link to={{ name: "pathway", id: reaction.pathway_id.value }}>
                        {reaction.pathway_id.value.replace("YAA:PWY:", "")}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </Cell>
                  <Cell className="font-mono text-[11px] text-zinc-400">
                    {reaction.compartment_id ? (
                      <ValueView v={reaction.compartment_id} mono showZone={false} />
                    ) : (
                      "—"
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel title="Functional annotation" subtitle={`${(data.annotations ?? []).length} term(s)`}>
        {(data.annotations ?? []).length === 0 ? (
          <Empty>no functional annotation is held for this gene</Empty>
        ) : (
          <div className="space-y-4">
            {[...byNamespace.entries()].map(([namespace, annotations]) => (
              <div key={namespace}>
                <h3 className="mb-1.5 font-mono text-xs uppercase tracking-wider text-zinc-500">
                  {namespace} <span className="text-zinc-700">({annotations.length})</span>
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {annotations.map((annotation) => (
                    <span
                      key={`${annotation.source}-${annotation.term_id}`}
                      title={`${annotation.source} · ${annotation.term_id}`}
                      className="rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1 text-[11px] text-zinc-300"
                    >
                      {isKnown(annotation.term_label)
                        ? annotation.term_label.value
                        : annotation.term_id}
                      <span className="ml-1.5 font-mono text-[10px] text-zinc-600">
                        {annotation.term_id}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {Object.keys(data.absent_sections ?? {}).length > 0 && (
        <Panel
          title="What this page cannot show"
          subtitle="sections PLAN.md P.2 designs for this page, and why each is empty"
        >
          <dl className="space-y-2">
            {Object.entries(data.absent_sections).map(([section, reason]) => (
              <div key={section} className="rounded border border-dashed border-zinc-800 px-3 py-2">
                <dt className="text-xs font-medium capitalize text-zinc-400">
                  {section.replace(/_/g, " ")}
                </dt>
                <dd className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">{reason}</dd>
              </div>
            ))}
          </dl>
          <Caveat tone="info">
            These sections are listed rather than omitted. An omitted section and an empty one look
            identical on a page, and only one of them is a statement about the atlas.
          </Caveat>
        </Panel>
      )}
    </div>
  );
}
