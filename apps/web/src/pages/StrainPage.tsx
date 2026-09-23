/**
 * Strains: the browse list, and one strain in full.
 *
 * PLAN.md P.2 names what this page must get right — "the lineage DAG and the condition-class
 * faceting of phenotype" — and the atlas holds nothing for the first. That is the whole reason
 * the lineage panel is written the way it is:
 *
 * `strain_lineage` has **zero rows**, so there is no DAG to draw for any strain in the atlas.
 * An empty SVG, or a box with nothing in it, asserts something false — JWY03 is a derivative of
 * JWY0 by construction, and every engineered strain has a parent. So the panel renders the
 * absence as an explicit state, in the same dashed style the rest of the interface uses for
 * "not recorded", with the server's own sentence saying that this is a statement about the
 * atlas rather than about the strain. When edges do appear the same panel draws them as a DAG.
 *
 * Phenotype is grouped by comparability class rather than listed and sorted. Every group today
 * is the single `unclassified` one — no measurement carries a `sample_id` — and it is drawn with
 * its rows in id order and no "best" anywhere on the page. Sorting by magnitude inside a group
 * with no class would be the leaderboard PLAN.md I.2 refuses, wearing a smaller hat.
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowLeft, CornerDownRight } from "lucide-react";

import { ClassHeader, NotRecorded } from "@/components/Comparability";
import { Caveat, Field, QuantityView, ValueView } from "@/components/Value";
import {
  BarList,
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
import { api, isKnown, type Lineage, type PhenotypeGroup } from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

export function StrainsPage({ route }: { route: Extract<Route, { name: "strains" }> }) {
  const strains = useQuery({
    queryKey: ["strains", route.q, route.cls],
    queryFn: () => api.strains({ q: route.q, class: route.cls, limit: 100 }),
  });

  if (strains.isLoading) return <Loading what="the strains" />;
  if (strains.error) return <ErrorBox error={strains.error} />;
  const data = strains.data!;

  const withLineage = data.rows.filter((row) => row.has_lineage).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Strains"
        lede="Every strain the atlas holds, with what hangs off each one. The counts are the
              useful part: a strain with no measurement, no modification and no genotype is a
              name that was extracted from a paper and nothing more."
      />

      <StatGrid>
        <Stat label="Strains" value={data.total} hint={`${data.count} shown`} />
        <Stat
          label="With a genotype"
          value={data.rows.filter((row) => row.has_genotype).length}
          hint="of the strains on this page"
        />
        <Stat
          label="With a lineage edge"
          value={withLineage}
          tone={withLineage === 0 ? "warn" : "good"}
          hint="`strain_lineage` is empty across the whole atlas"
        />
        <Stat
          label="With a measurement"
          value={data.rows.filter((row) => row.measurements > 0).length}
          hint="the rest carry a name and nothing quantitative"
        />
      </StatGrid>

      <div className="grid gap-6 lg:grid-cols-4">
        <Panel
          title="Class"
          subtitle="atlas-wide, not narrowed by the filter"
          className="lg:col-span-1"
        >
          <BarList
            data={Object.entries(data.by_class).sort((a, b) => b[1] - a[1])}
            onSelect={(key) =>
              navigate({
                name: "strains",
                q: route.q,
                cls: key === route.cls || key === "not recorded" ? undefined : key,
              })
            }
          />
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
            `class` is curated and frequently arguable (PLAN.md C.2), which is why it carries its
            own evidence on every row rather than being a bare enum.
          </p>
        </Panel>

        <Panel
          title="All strains"
          subtitle={
            route.cls ? `class = ${route.cls}` : "ordered by name, not by anything measured"
          }
          className="lg:col-span-3"
          right={
            (route.cls || route.q) && (
              <button
                onClick={() => navigate({ name: "strains" })}
                className="text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                clear filter
              </button>
            )
          }
        >
          {data.rows.length === 0 ? (
            <Empty>no strain matches this filter</Empty>
          ) : (
            <Table head={["Strain", "Class", "Measurements", "Modifications", "Samples", "Has"]}>
              {data.rows.map((row) => (
                <Row key={row.id}>
                  <Cell>
                    <Link to={{ name: "strain", id: row.id }}>{row.canonical_name}</Link>
                  </Cell>
                  <Cell className="text-xs">
                    <ValueView v={row.strain_class} showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-xs tabular-nums">{row.measurements || "—"}</Cell>
                  <Cell className="font-mono text-xs tabular-nums">{row.modifications || "—"}</Cell>
                  <Cell className="font-mono text-xs tabular-nums">{row.samples || "—"}</Cell>
                  <Cell className="text-[11px] text-zinc-500">
                    {[row.has_genotype && "genotype", row.has_lineage && "lineage"]
                      .filter(Boolean)
                      .join(", ") || "—"}
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
          {data.truncated && (
            <p className="mt-3 text-[11px] text-zinc-500">
              {data.count} of {data.total} — this is a page, not a total.
            </p>
          )}
        </Panel>
      </div>
    </div>
  );
}

/**
 * The lineage panel.
 *
 * Draws a DAG when there is one — parents above, children below, this strain between them — and
 * an explicit "no lineage recorded" state when there is not. Never an empty frame.
 */
function LineagePanel({ lineage, name }: { lineage: Lineage; name: string }) {
  if (!lineage.is_recorded) {
    return (
      <Panel title="Lineage" subtitle="parents and derivatives, as a DAG">
        <div className="space-y-3">
          <Empty>no lineage recorded</Empty>
          <Caveat>{lineage.note}</Caveat>
        </div>
      </Panel>
    );
  }

  const node = (label: string, id: string, step?: unknown) => (
    <div key={id} className="rounded border border-zinc-800 bg-zinc-900/60 px-3 py-1.5">
      <Link to={{ name: "strain", id }} className="text-sm">
        {label}
      </Link>
      {typeof step === "string" && (
        <div className="mt-0.5 text-[10px] uppercase tracking-wide text-zinc-500">{step}</div>
      )}
    </div>
  );

  return (
    <Panel title="Lineage" subtitle={lineage.note}>
      <div className="space-y-3">
        {lineage.parents.length > 0 && (
          <div className="space-y-2">
            <div className="text-[10px] uppercase tracking-wider text-zinc-600">parents</div>
            <div className="flex flex-wrap gap-2">
              {lineage.parents.map((parent) =>
                node(
                  String(parent.canonical_name ?? parent.strain_id),
                  String(parent.strain_id),
                  parent.step_type,
                ),
              )}
            </div>
            <ArrowDown className="h-3.5 w-3.5 text-zinc-700" />
          </div>
        )}
        <div className="inline-block rounded border border-sky-700/50 bg-sky-950/30 px-3 py-1.5 text-sm text-sky-100">
          {name}
        </div>
        {lineage.children.length > 0 && (
          <div className="space-y-2">
            <CornerDownRight className="h-3.5 w-3.5 text-zinc-700" />
            <div className="text-[10px] uppercase tracking-wider text-zinc-600">derivatives</div>
            <div className="flex flex-wrap gap-2">
              {lineage.children.map((child) =>
                node(
                  String(child.canonical_name ?? child.strain_id),
                  String(child.strain_id),
                  child.step_type,
                ),
              )}
            </div>
          </div>
        )}
      </div>
    </Panel>
  );
}

/** One comparability class's measurements. Never sorted by value; see the file header. */
function PhenotypeClass({ group }: { group: PhenotypeGroup }) {
  return (
    <div className="space-y-2 rounded border border-zinc-800/70 p-3">
      <ClassHeader
        klass={group.class}
        right={
          <span className="shrink-0 text-[11px] text-zinc-500">
            {group.count} measurement{group.count === 1 ? "" : "s"}
            {group.units.length > 1 && (
              <span className="ml-2 text-amber-400/80">{group.units.length} units</span>
            )}
          </span>
        }
      />
      <Table head={["Value", "Kind", "Product", "Basis", "Source", "Caveats"]}>
        {group.measurements.map((row) => (
          <Row key={row.id}>
            <Cell>
              <QuantityView q={row.quantity} />
            </Cell>
            <Cell className="text-xs">
              <span className={row.is_controlled_kind ? "text-zinc-300" : "text-amber-300/80"}>
                {row.quantity_kind.length > 30
                  ? `${row.quantity_kind.slice(0, 30)}…`
                  : row.quantity_kind}
              </span>
            </Cell>
            <Cell className="text-[11px]">
              {isKnown(row.product_id) ? (
                <Link to={{ name: "product", id: row.product_id.value }}>
                  {row.product_id.value.replace("YAA:PRODUCT:", "")}
                </Link>
              ) : (
                <ValueView v={row.product_id} showZone={false} />
              )}
            </Cell>
            <Cell className="text-[11px]">
              <ValueView v={row.basis} showZone={false} />
            </Cell>
            <Cell className="text-[11px]">
              {isKnown(row.publication_id) ? (
                <Link to={{ name: "publication", id: row.publication_id.value }}>paper</Link>
              ) : (
                <ValueView v={row.publication_id} showZone={false} />
              )}
            </Cell>
            <Cell>
              {row.comparability_warnings.length === 0 ? (
                <span className="text-[11px] text-zinc-600">—</span>
              ) : (
                <details className="text-[11px]">
                  <summary className="cursor-pointer text-amber-400/80">
                    {row.comparability_warnings.length}
                  </summary>
                  <ul className="mt-1.5 space-y-1 text-zinc-500">
                    {row.comparability_warnings.map((warning, index) => (
                      <li key={index} className="leading-snug">
                        · {warning}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </Cell>
          </Row>
        ))}
      </Table>
    </div>
  );
}

export function StrainPage({ id }: { id: string }) {
  const strain = useQuery({ queryKey: ["strain", id], queryFn: () => api.strain(id) });

  if (strain.isLoading) return <Loading what="the strain" />;
  if (strain.error) return <ErrorBox error={strain.error} />;
  const data = strain.data!;

  const measurements = data.phenotype.reduce((total, group) => total + group.count, 0);

  return (
    <div className="space-y-6">
      <Link to={{ name: "strains" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Strains
      </Link>

      <header>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-50">
          {data.canonical_name}
        </h1>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-400">
          <ValueView v={data.organism_name} showZone={false} />
          <span className="text-zinc-700">·</span>
          <ValueView v={data.strain_class} />
          <span className="text-zinc-700">·</span>
          <span className="font-mono text-xs text-zinc-600">{data.id}</span>
        </p>
        {data.aliases.length > 0 && (
          <p className="mt-1 text-xs text-zinc-500">
            also known as {data.aliases.map((alias) => alias.alias).join(", ")}
          </p>
        )}
      </header>

      <StatGrid>
        <Stat label="Measurements" value={measurements} hint={`in ${data.phenotype.length} class(es)`} />
        <Stat label="Modifications" value={data.modifications.length} hint="recorded engineering steps" />
        <Stat
          label="Lineage edges"
          value={data.lineage.parents.length + data.lineage.children.length}
          tone={data.lineage.is_recorded ? "good" : "warn"}
          hint={data.lineage.is_recorded ? "recorded" : "none recorded — not the same as none"}
        />
        <Stat label="Samples" value={data.samples.length} hint="sequencing samples naming this strain" />
      </StatGrid>

      <div className="grid gap-6 lg:grid-cols-2">
        <LineagePanel lineage={data.lineage} name={data.canonical_name} />

        <Panel title="Genotype" subtitle="the source's own string, and the parse beside it">
          {data.genotype.length === 0 ? (
            <Empty>no genotype recorded for this strain</Empty>
          ) : (
            <div className="space-y-4">
              {data.genotype.map((genotype) => {
                const parsed = genotype.parsed;
                const parts = Array.isArray(parsed?.parts) ? (parsed.parts as Record<string, unknown>[]) : [];
                const deletions = Array.isArray(parsed?.deletions) ? (parsed.deletions as string[]) : [];
                return (
                  <div key={genotype.id} className="space-y-2">
                    <p className="rounded border border-zinc-800 bg-zinc-950/60 px-3 py-2 font-mono text-xs leading-relaxed text-zinc-200">
                      {genotype.as_reported}
                    </p>
                    {parsed === null ? (
                      <p className="text-[11px] text-amber-400/80">
                        no parse is stored for this genotype; the verbatim string above is the
                        Zone R record and stands on its own.
                      </p>
                    ) : (
                      <div className="flex flex-wrap gap-1.5">
                        {deletions.map((deletion) => (
                          <span
                            key={`del-${deletion}`}
                            className="rounded bg-red-500/10 px-1.5 py-0.5 font-mono text-[10px] text-red-300"
                          >
                            Δ{deletion}
                          </span>
                        ))}
                        {parts.map((part, index) => (
                          <span
                            key={`part-${index}`}
                            title={String(part.as_reported ?? "")}
                            className="rounded bg-zinc-800 px-1.5 py-0.5 font-mono text-[10px] text-zinc-300"
                          >
                            {String(part.kind ?? "part")}: {String(part.target ?? "?")}
                          </span>
                        ))}
                        {parsed.fully_parsed === false && (
                          <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                            parse incomplete
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </Panel>
      </div>

      <Panel
        title="Modifications"
        subtitle="what was done to this strain, and what was verified about it"
      >
        {data.modifications.length === 0 ? (
          <Empty>
            no modification is recorded for this strain. The atlas holds 10 modifications in
            total, so this is far more often an unfilled record than a genuinely unmodified
            strain.
          </Empty>
        ) : (
          <Table head={["Type", "Target", "Detail", "Verification", "Source"]}>
            {data.modifications.map((mod) => {
              const verification = mod.subtype.verification_method;
              return (
                <Row key={mod.id}>
                  <Cell className="whitespace-nowrap text-xs text-zinc-200">{mod.type}</Cell>
                  <Cell className="font-mono text-[11px]">
                    <ValueView v={mod.target_locus} mono showZone={false} />
                  </Cell>
                  <Cell className="max-w-md text-[11px] leading-relaxed">
                    <ValueView v={mod.details} showZone={false} />
                  </Cell>
                  <Cell className="text-[11px]">
                    {verification === undefined ? (
                      <span className="text-zinc-600">—</span>
                    ) : (
                      <span
                        className={
                          verification === "none_reported" ? "text-amber-400/90" : "text-zinc-300"
                        }
                        title={
                          verification === "none_reported"
                            ? "a claimed relocalization nobody verified may simply not be imported"
                            : undefined
                        }
                      >
                        {String(verification)}
                      </span>
                    )}
                  </Cell>
                  <Cell className="text-[11px]">
                    {isKnown(mod.publication_id) ? (
                      <Link to={{ name: "publication", id: mod.publication_id.value }}>paper</Link>
                    ) : (
                      <ValueView v={mod.publication_id} showZone={false} />
                    )}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Panel>

      <Panel
        title="Production phenotype"
        subtitle="grouped by comparability class — never ranked across one"
        right={
          <Link
            to={{ name: "compare", kind: "strain", ids: [data.id] }}
            className="text-[11px]"
          >
            compare with another strain
          </Link>
        }
      >
        {data.phenotype.length === 0 ? (
          <Empty>no measurement in the atlas names this strain</Empty>
        ) : (
          <div className="space-y-4">
            {data.phenotype.map((group) => (
              <PhenotypeClass key={group.class.key} group={group} />
            ))}
            {data.phenotype_truncated && (
              <p className="text-[11px] text-zinc-500">This is a page, not a total.</p>
            )}
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Tolerance profile" subtitle="what the atlas can record about tolerance">
          {data.tolerance.length === 0 ? (
            <div className="space-y-3">
              <Empty>no tolerance recorded</Empty>
              <Caveat>{data.tolerance_note}</Caveat>
            </div>
          ) : (
            <dl>
              {data.tolerance.map((profile) => (
                <Field key={profile.id} label={profile.name_as_reported}>
                  {/* The raw chassis_profile columns, read through the same three-state rule the
                      schema enforces: a number only where the state says 'recorded'. */}
                  {profile.isobutanol_tolerance_state === "recorded" ? (
                    <span className="font-mono text-sm text-zinc-100">
                      {profile.isobutanol_tolerance_g_l} g/L
                    </span>
                  ) : (
                    <NotRecorded why="chassis_profile.isobutanol_tolerance_g_l is not recorded" />
                  )}
                </Field>
              ))}
            </dl>
          )}
        </Panel>

        <Panel title="Transcriptome" subtitle="samples in the atlas that name this strain">
          <div className="space-y-3">
            {data.samples.length === 0 ? (
              <Empty>no sample names this strain</Empty>
            ) : (
              <Table head={["Sample", "Experiment", "Context"]}>
                {data.samples.slice(0, 12).map((sample) => (
                  <Row key={String(sample.id)}>
                    <Cell className="font-mono text-[11px]">{String(sample.id)}</Cell>
                    <Cell className="text-[11px]">
                      {sample.experiment_id ? (
                        <Link to={{ name: "experiment", id: String(sample.experiment_id) }}>
                          {String(sample.experiment_id).replace("YAA:EXPERIMENT:", "")}
                        </Link>
                      ) : (
                        <span className="text-zinc-600">—</span>
                      )}
                    </Cell>
                    <Cell className="font-mono text-[10px] text-zinc-500">
                      {sample.condition_context_id
                        ? String(sample.condition_context_id).replace("YAA:CCTX:", "")
                        : "none"}
                    </Cell>
                  </Row>
                ))}
              </Table>
            )}
            <Caveat tone="info">{data.transcriptome_note}</Caveat>
          </div>
        </Panel>
      </div>

      <Panel title="Publications" subtitle="papers that contributed a fact about this strain">
        {data.publications.length === 0 ? (
          <Empty>no publication is linked to this strain through a measurement or a modification</Empty>
        ) : (
          <ul className="space-y-1.5">
            {data.publications.map((publication) => (
              <li key={publication}>
                <Link to={{ name: "publication", id: publication }} className="font-mono text-xs">
                  {publication}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel title="Provenance" subtitle="how this row got here">
        <dl>
          <Field label="Zone">
            <ValueView v={data.zone} />
          </Field>
          <Field label="Confidence">
            <ValueView v={data.confidence} showZone={false} />
          </Field>
          <Field label="Evidence">
            <span className="text-[11px] leading-relaxed text-zinc-400">
              <ValueView v={data.evidence} showZone={false} />
            </span>
          </Field>
        </dl>
      </Panel>
    </div>
  );
}
