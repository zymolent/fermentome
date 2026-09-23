/**
 * Experiments: the browse list, and one experiment in full.
 *
 * PLAN.md P.2's brief for this page is a brief about absence — "the condition context in full,
 * with 'not recorded' visible" — so the condition panel renders every one of the 19 facets
 * whether or not anything was recorded for it, and the three absences render as three different
 * things. A table of the two facets somebody happened to fill in looks like a well-described
 * experiment. Nineteen rows of which eighteen say "not recorded" looks like what it is.
 *
 * The other thing this page does that no other page does is render `experiment.evidence` as
 * content rather than as metadata. Every experiment row in the atlas was derived from an SRA
 * study, and its `evidence` column holds the paragraph explaining why the publication link was
 * *refused* — that SRA runinfo's `Study_Pubmed_id` is a legacy link-type code and not a PMID,
 * and that a full-text mention of an accession is a citation, not a deposit. That paragraph is
 * the most useful thing on the page: it is the difference between "nobody looked" and "somebody
 * looked, and declined to assert the link".
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { ContextPanel } from "@/components/Comparability";
import { Caveat, Field, QuantityView, ValueView } from "@/components/Value";
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
import { api, isKnown } from "@/lib/api";
import { type Route } from "@/lib/router";

export function ExperimentsPage({ route }: { route: Extract<Route, { name: "experiments" }> }) {
  const experiments = useQuery({
    queryKey: ["experiments", route.q],
    queryFn: () => api.experiments({ q: route.q, limit: 100 }),
  });

  if (experiments.isLoading) return <Loading what="the experiments" />;
  if (experiments.error) return <ErrorBox error={experiments.error} />;
  const data = experiments.data!;

  const withPublication = data.rows.filter((row) => isKnown(row.publication_id)).length;
  const withContext = data.rows.filter((row) => row.samples_with_context > 0).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Experiments"
        lede="Every experiment the atlas holds. All of them were derived from a deposited SRA
              study rather than read out of a paper, which is why the design columns are empty and
              why none of them names a publication — each row carries the reason it does not."
      />

      <StatGrid>
        <Stat label="Experiments" value={data.count} hint="one per SRA study" />
        <Stat
          label="Naming a publication"
          value={withPublication}
          tone={withPublication === 0 ? "warn" : "good"}
          hint="the link is refused, not missing — see any experiment's provenance"
        />
        <Stat
          label="With a condition context"
          value={withContext}
          tone={withContext === 0 ? "warn" : "default"}
          hint="at least one sample reaching a context"
        />
        <Stat
          label="With a measurement"
          value={data.rows.filter((row) => row.measurements > 0).length}
          tone="warn"
          hint="no measurement in the atlas carries an experiment_id"
        />
      </StatGrid>

      <Panel title="All experiments" subtitle="ordered by id">
        {data.rows.length === 0 ? (
          <Empty>no experiment matches this filter</Empty>
        ) : (
          <Table head={["Experiment", "Design", "Objective", "Samples", "With context", "Paper"]}>
            {data.rows.map((row) => (
              <Row key={row.id}>
                <Cell>
                  <Link to={{ name: "experiment", id: row.id }} className="font-mono text-xs">
                    {row.id.replace("YAA:EXPERIMENT:", "")}
                  </Link>
                </Cell>
                <Cell className="text-xs">
                  <ValueView v={row.design_type} showZone={false} />
                </Cell>
                <Cell className="max-w-sm text-xs">
                  <ValueView v={row.objective} showZone={false} />
                </Cell>
                <Cell className="font-mono text-xs tabular-nums">{row.samples}</Cell>
                <Cell
                  className={`font-mono text-xs tabular-nums ${
                    row.samples_with_context === 0 ? "text-zinc-600" : "text-zinc-300"
                  }`}
                >
                  {row.samples_with_context}
                </Cell>
                <Cell className="text-[11px]">
                  {isKnown(row.publication_id) ? (
                    <Link to={{ name: "publication", id: row.publication_id.value }}>paper</Link>
                  ) : (
                    <ValueView v={row.publication_id} showZone={false} />
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        {data.truncated && (
          <p className="mt-3 text-[11px] text-zinc-500">This is a page, not a total.</p>
        )}
      </Panel>
    </div>
  );
}

export function ExperimentPage({ id }: { id: string }) {
  const experiment = useQuery({ queryKey: ["experiment", id], queryFn: () => api.experiment(id) });

  if (experiment.isLoading) return <Loading what="the experiment" />;
  if (experiment.error) return <ErrorBox error={experiment.error} />;
  const data = experiment.data!;

  const quarantined = data.quality_flags.filter((flag) => flag.severity === "quarantine");

  return (
    <div className="space-y-6">
      <Link to={{ name: "experiments" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Experiments
      </Link>

      <header>
        <h1 className="font-mono text-lg font-semibold tracking-tight text-zinc-50">
          {data.id.replace("YAA:EXPERIMENT:", "")}
        </h1>
        <p className="mt-1.5 text-sm text-zinc-400">
          <ValueView v={data.objective} showZone={false} />
        </p>
      </header>

      <StatGrid>
        <Stat label="Samples" value={data.samples.length} />
        <Stat
          label="Reaching a context"
          value={data.samples_with_context}
          tone={data.samples_with_context === 0 ? "warn" : "good"}
          hint={`${data.contexts.length} distinct context(s)`}
        />
        <Stat label="Datasets" value={data.datasets.length} hint={`${data.analyses.length} analyses`} />
        <Stat
          label="Measurements"
          value={data.measurements.length}
          tone={data.measurements.length === 0 ? "warn" : "default"}
          hint="production metrics attached to this experiment"
        />
      </StatGrid>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Design" subtitle="what the atlas records about how this was run">
          <dl>
            <Field label="Design type">
              <ValueView v={data.design_type} />
            </Field>
            <Field label="Objective">
              <ValueView v={data.objective} />
            </Field>
            <Field label="Publication">
              {isKnown(data.publication_id) ? (
                <Link to={{ name: "publication", id: data.publication_id.value }}>
                  {isKnown(data.publication_title)
                    ? data.publication_title.value
                    : data.publication_id.value}
                </Link>
              ) : (
                <ValueView v={data.publication_id} />
              )}
            </Field>
            <Field label="Zone">
              <ValueView v={data.zone} />
            </Field>
            <Field label="Confidence">
              <ValueView v={data.confidence} showZone={false} />
            </Field>
          </dl>
        </Panel>

        <Panel
          title="Why this row says what it says"
          subtitle="the experiment's own evidence string, rendered as content"
        >
          <p className="whitespace-pre-line text-xs leading-relaxed text-zinc-400">
            <ValueView v={data.evidence} showZone={false} />
          </p>
        </Panel>
      </div>

      <ContextPanel contexts={data.contexts} note={data.context_note} />

      <Panel title="Samples" subtitle={`${data.samples.length} sample(s)`}>
        {data.samples.length === 0 ? (
          <Empty>no sample names this experiment</Empty>
        ) : (
          <Table head={["Sample", "Strain", "Context", "Time", "Growth phase", "Flags"]}>
            {data.samples.slice(0, 60).map((sample) => {
              const flags = data.quality_flags.filter((flag) => flag.target_id === sample.id);
              return (
                <Row key={sample.id}>
                  <Cell className="font-mono text-[11px]">{sample.id}</Cell>
                  <Cell className="text-[11px]">
                    {sample.strain_id ? (
                      <Link to={{ name: "strain", id: sample.strain_id }}>
                        {sample.strain_name ?? sample.strain_id}
                      </Link>
                    ) : (
                      <span className="italic text-zinc-500 underline decoration-dashed decoration-zinc-600 underline-offset-2">
                        not recorded
                      </span>
                    )}
                  </Cell>
                  <Cell className="font-mono text-[10px] text-zinc-500">
                    {sample.condition_context_id ? (
                      sample.condition_context_id.replace("YAA:CCTX:", "")
                    ) : (
                      <span className="italic text-zinc-500 underline decoration-dashed decoration-zinc-600 underline-offset-2">
                        none
                      </span>
                    )}
                  </Cell>
                  <Cell className="font-mono text-[11px] tabular-nums">
                    {sample.time_h === null ? (
                      <span className="text-zinc-600">—</span>
                    ) : (
                      `${sample.time_h} h`
                    )}
                  </Cell>
                  <Cell className="text-[11px]">
                    {sample.growth_phase ?? <span className="text-zinc-600">—</span>}
                  </Cell>
                  <Cell className="text-[11px]">
                    {flags.length === 0 ? (
                      <span className="text-zinc-600">—</span>
                    ) : (
                      <span
                        className={
                          flags.some((flag) => flag.severity === "quarantine")
                            ? "text-red-400"
                            : "text-amber-400/80"
                        }
                        title={flags.map((flag) => `${flag.kind}: ${flag.rationale}`).join("\n")}
                      >
                        {flags.map((flag) => flag.kind).join(", ")}
                      </span>
                    )}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
        {data.samples.length > 60 && (
          <p className="mt-3 text-[11px] text-zinc-500">
            First 60 of {data.samples.length}; this is a page, not a total.
          </p>
        )}
        {quarantined.length > 0 && (
          <div className="mt-4">
            <Caveat>
              {quarantined.length} sample(s) in this experiment are quarantined:{" "}
              {quarantined[0].rationale ?? quarantined[0].kind}
            </Caveat>
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Omics" subtitle="the deposits this experiment's samples came from">
          {data.datasets.length === 0 ? (
            <Empty>no dataset is linked to this experiment&apos;s samples</Empty>
          ) : (
            <Table head={["Dataset", "Repository", "Type", "Platform"]}>
              {data.datasets.map((dataset) => (
                <Row key={String(dataset.id)}>
                  <Cell className="font-mono text-[11px]">{String(dataset.accession ?? dataset.id)}</Cell>
                  <Cell className="text-[11px]">{String(dataset.repository ?? "—")}</Cell>
                  <Cell className="text-[11px]">{String(dataset.omics_type ?? "—")}</Cell>
                  <Cell className="text-[11px]">{String(dataset.platform ?? "—")}</Cell>
                </Row>
              ))}
            </Table>
          )}
          {data.analyses.length > 0 && (
            <div className="mt-4 space-y-1">
              <div className="text-[10px] uppercase tracking-wider text-zinc-600">analyses</div>
              {data.analyses.map((analysis) => (
                <div key={String(analysis.id)} className="font-mono text-[11px] text-zinc-400">
                  {String(analysis.kind)} · {String(analysis.payload_ref)}
                </div>
              ))}
            </div>
          )}
        </Panel>

        <Panel title="Production metrics" subtitle="numbers attached to this experiment">
          {data.measurements.length === 0 ? (
            <div className="space-y-3">
              <Empty>no measurement names this experiment</Empty>
              <Caveat>{data.measurement_note}</Caveat>
            </div>
          ) : (
            <Table head={["Value", "Kind", "Product", "Source"]}>
              {data.measurements.map((row) => (
                <Row key={row.id}>
                  <Cell>
                    <QuantityView q={row.quantity} />
                  </Cell>
                  <Cell className="text-xs">{row.quantity_kind}</Cell>
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
                    <ValueView v={row.source_locator} showZone={false} />
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>
    </div>
  );
}
