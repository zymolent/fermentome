/**
 * One route, and one pathway. Two small detail pages that share a file because they share a
 * shape: a step list with compartments, and a caveat about what the scoring does not cover.
 *
 * The route page draws its steps as an ordered chain with the compartment and the genetic code
 * on each, because a route that crosses into the matrix at step 3 has a recoding requirement at
 * step 3, and a flat table makes that a thing you have to notice rather than a thing you see.
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { Caveat, Field, ValueView } from "@/components/Value";
import {
  Cell,
  Empty,
  ErrorBox,
  Link,
  Loading,
  Panel,
  Row,
  Stat,
  StatGrid,
  Table,
} from "@/components/ui";
import { api, isKnown, type Value } from "@/lib/api";

interface Step {
  step_order: number;
  step_role_id: string;
  part_id: string | null;
  compartment_id: string | null;
  encoding_genome: string | null;
}

interface RouteDetail {
  id: string;
  cofactor_strategy: Value<string>;
  balance_status: Value<string>;
  host_strain_id: Value<string>;
  deletion_set: Value<string>;
  scores: Record<string, Value<number>>;
  scored_axes: string[];
  unscored_axes: string[];
  is_viable: boolean;
  steps: Step[];
  compartments: string[];
  uses_mitochondrial_code: boolean;
  ranking_caveat?: string;
}

const COMPARTMENT_TINT: Record<string, string> = {
  cytosol: "border-sky-700/50 bg-sky-950/30",
  mitochondrial_matrix: "border-amber-700/50 bg-amber-950/20",
  mitochondrial_inner_membrane: "border-orange-700/50 bg-orange-950/20",
  peroxisome: "border-violet-700/50 bg-violet-950/20",
};

export function RoutePage({ id }: { id: string }) {
  const route = useQuery({
    queryKey: ["route", id],
    queryFn: () => api.route(id) as unknown as Promise<RouteDetail>,
  });

  if (route.isLoading) return <Loading what="the route" />;
  if (route.error) return <ErrorBox error={route.error} />;
  const data = route.data as unknown as RouteDetail;

  return (
    <div className="space-y-6">
      <Link to={{ name: "networks" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Networks
      </Link>

      <header>
        <h1 className="font-mono text-lg font-semibold tracking-tight text-zinc-50">
          {data.id.replace("YAA:ROUTE:", "")}
        </h1>
        <p className="mt-1 text-sm text-zinc-400">
          <ValueView v={data.cofactor_strategy} showZone={false} />
        </p>
      </header>

      <StatGrid>
        <Stat
          label="Balance check"
          value={isKnown(data.balance_status) ? data.balance_status.value : "—"}
          tone={data.is_viable ? "good" : "warn"}
          hint={data.is_viable ? "this route balances" : "nothing else makes a route usable"}
        />
        <Stat label="Steps" value={data.steps.length} hint={data.compartments.join(", ")} />
        <Stat
          label="Uses table 3"
          value={data.uses_mitochondrial_code ? "yes" : "no"}
          tone={data.uses_mitochondrial_code ? "warn" : "default"}
          hint={
            data.uses_mitochondrial_code
              ? "a step is mtDNA-encoded — recoding is required"
              : "every step is nuclear-encoded"
          }
        />
        <Stat
          label="Scored axes"
          value={`${data.scored_axes.length} / ${data.scored_axes.length + data.unscored_axes.length}`}
          tone={data.unscored_axes.length > 0 ? "warn" : "good"}
          hint={data.unscored_axes.join(", ") || "all axes computed"}
        />
      </StatGrid>

      {data.ranking_caveat && <Caveat>{data.ranking_caveat}</Caveat>}

      <Panel title="Steps" subtitle="in order, with the compartment and code table each runs under">
        {data.steps.length === 0 ? (
          <Empty>no steps recorded for this route</Empty>
        ) : (
          <ol className="flex flex-wrap items-stretch gap-2">
            {[...data.steps]
              .sort((a, b) => a.step_order - b.step_order)
              .map((step, index, all) => (
                <li key={step.step_order} className="flex items-center gap-2">
                  <div
                    className={`rounded border px-3 py-2 ${
                      COMPARTMENT_TINT[step.compartment_id ?? ""] ?? "border-zinc-800 bg-zinc-900/40"
                    }`}
                  >
                    <div className="text-sm font-medium text-zinc-100">{step.step_role_id}</div>
                    <div className="mt-0.5 font-mono text-[10px] text-zinc-500">
                      {step.compartment_id ?? "no compartment"}
                    </div>
                    {step.part_id && (
                      <div className="mt-1 truncate font-mono text-[10px] text-zinc-400">
                        {step.part_id.replace("YAA:PART:", "")}
                      </div>
                    )}
                    {step.encoding_genome === "mitochondrial" && (
                      <div className="mt-1 rounded bg-amber-500/15 px-1 py-0.5 text-center text-[9px] uppercase tracking-wide text-amber-300">
                        table 3
                      </div>
                    )}
                  </div>
                  {index < all.length - 1 && (
                    <ArrowRight className="h-3.5 w-3.5 shrink-0 text-zinc-700" />
                  )}
                </li>
              ))}
          </ol>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Scores" subtitle="per axis — a missing axis is not a zero">
          <dl>
            {Object.entries(data.scores).map(([axis, value]) => (
              <Field key={axis} label={axis.replace("score_", "")}>
                <ValueView v={value} mono />
              </Field>
            ))}
          </dl>
        </Panel>
        <Panel title="Binding" subtitle="what this route is proposed against">
          <dl>
            <Field label="Host strain">
              <ValueView v={data.host_strain_id} mono />
            </Field>
            <Field label="Deletion set">
              <ValueView v={data.deletion_set} mono />
            </Field>
          </dl>
          {!isKnown(data.host_strain_id) && (
            <Caveat tone="info">
              No host strain is bound, so this route is a shape rather than a proposal against a
              particular background. Feasibility in a specific chassis is not what these scores
              measure.
            </Caveat>
          )}
        </Panel>
      </div>
    </div>
  );
}

interface PathwayDetail {
  id: string;
  name?: Value<string>;
  reactions?: Record<string, unknown>[];
  [key: string]: unknown;
}

export function PathwayPage({ id }: { id: string }) {
  const pathway = useQuery({
    queryKey: ["pathway", id],
    queryFn: () => api.pathway(id) as unknown as Promise<PathwayDetail>,
  });
  const graph = useQuery({ queryKey: ["graph", id], queryFn: () => api.graph(id) });

  if (pathway.isLoading) return <Loading what="the pathway" />;
  if (pathway.error) return <ErrorBox error={pathway.error} />;
  const data = pathway.data as unknown as PathwayDetail;

  const reactions = (data.reactions ?? []) as Record<string, unknown>[];

  return (
    <div className="space-y-6">
      <Link to={{ name: "networks" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Networks
      </Link>

      <header>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-50">
          {data.name && isKnown(data.name) ? data.name.value : data.id}
        </h1>
        <p className="mt-1 font-mono text-xs text-zinc-500">{data.id}</p>
      </header>

      <Panel title="Reactions" subtitle={`${reactions.length} reaction(s) in this pathway`}>
        {reactions.length === 0 ? (
          <Empty>no reactions are attached to this pathway</Empty>
        ) : (
          <Table head={["Reaction", "EC", "Compartment", "Reversible"]}>
            {reactions.map((reaction, index) => {
              const name = reaction.name as Value<string> | undefined;
              const ec = reaction.ec_number as Value<string> | undefined;
              const compartment = reaction.compartment_id as Value<string> | undefined;
              return (
                <Row key={String(reaction.id ?? index)}>
                  <Cell className="text-xs">
                    {name ? <ValueView v={name} showZone={false} /> : String(reaction.id ?? "—")}
                  </Cell>
                  <Cell className="font-mono text-[11px] text-zinc-400">
                    {ec ? <ValueView v={ec} mono showZone={false} /> : "—"}
                  </Cell>
                  <Cell className="font-mono text-[11px] text-zinc-400">
                    {compartment ? <ValueView v={compartment} mono showZone={false} /> : "—"}
                  </Cell>
                  <Cell className="text-xs text-zinc-500">
                    {reaction.reversible ? "reversible" : "irreversible"}
                  </Cell>
                </Row>
              );
            })}
          </Table>
        )}
      </Panel>

      {graph.data && graph.data.nodes.length > 0 && (
        <Panel title="Graph" subtitle="this pathway's reactions and their metabolites">
          <div className="text-[11px] text-zinc-500">
            {graph.data.nodes.length} nodes · {graph.data.edges.length} edges ·{" "}
            {graph.data.compartments.join(", ")}
          </div>
        </Panel>
      )}
    </div>
  );
}
