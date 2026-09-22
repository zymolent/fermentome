/**
 * Networks: the curated reaction graph, and the enumerated route space over it.
 *
 * The routes table is where a UI is most tempted to lie. 6,400 routes sorted by a composite
 * score looks like a shortlist; it is not one, for three reasons the page states rather than
 * buries:
 *
 *   - every route currently fails the balance check, so the "top" route is the best of 6,400
 *     non-viable ones;
 *   - `score_toxicity` was never computed, so a five-axis score would silently be a four-axis
 *     score;
 *   - no route is bound to a host strain, so a route is a shape, not a proposal.
 *
 * So the table ranks on one *named* axis, shows the axis in the header, and renders the missing
 * axis as "not recorded" rather than as zero.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ReactionGraphView } from "@/components/ReactionGraph";
import { Caveat } from "@/components/Value";
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
import { api } from "@/lib/api";

const AXES = [
  "score_evidence",
  "score_feasibility",
  "score_balance",
  "score_transport",
  "score_toxicity",
] as const;

/** A score cell. `null` is "never computed" and must not render as 0. */
function Score({ value }: { value: number | null }) {
  if (value === null) {
    return (
      <span
        className="text-[11px] italic text-zinc-600 underline decoration-dashed decoration-zinc-700 underline-offset-2"
        title="never computed — not the same as a score of zero"
      >
        not recorded
      </span>
    );
  }
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="h-1 w-8 overflow-hidden rounded-full bg-zinc-800">
        <span
          className="block h-full bg-sky-500/70"
          style={{ width: `${Math.max(0, Math.min(1, value)) * 100}%` }}
        />
      </span>
      <span className="font-mono text-[11px] tabular-nums text-zinc-400">{value.toFixed(2)}</span>
    </span>
  );
}

export function NetworksPage() {
  const [axis, setAxis] = useState<string>("score_evidence");
  const [strategy, setStrategy] = useState<string | undefined>();

  const overview = useQuery({ queryKey: ["networks"], queryFn: api.networks });
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => api.graph() });
  const routes = useQuery({
    queryKey: ["routes", axis, strategy],
    queryFn: () => api.routes({ order_by: axis, cofactor_strategy: strategy, limit: 25 }),
  });

  if (overview.isLoading) return <Loading what="the route space" />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const data = overview.data!;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Networks"
        lede="Two graphs live here. The curated reaction graph is small and hand-checked — it is what
              a pathway diagram is drawn from. The route space is generative: 6,400 enumerated
              combinations, most of which nobody has attempted, which is what makes 'what has never
              been tried' an answerable question."
      />

      <StatGrid>
        <Stat label="Reactions" value={data.reactions} hint={`${data.metabolites} metabolites`} />
        <Stat label="Routes enumerated" value={data.routes} hint="generative, not a list of published builds" />
        <Stat
          label="Passing the balance check"
          value={data.viable_routes}
          tone={data.viable_routes === 0 ? "warn" : "good"}
          hint={data.viable_routes === 0 ? "every enumerated route currently fails" : "viable routes"}
        />
        <Stat
          label="Open knowledge gaps"
          value={Object.values(data.gaps_by_kind).reduce((a, b) => a + b, 0)}
          tone="warn"
          hint={Object.keys(data.gaps_by_kind).join(", ")}
        />
      </StatGrid>

      {data.viable_routes === 0 && (
        <Caveat>
          All {data.routes.toLocaleString()} routes carry <code>balance_status = fail</code>. Any
          ranking below is therefore an ordering of non-viable routes — useful for seeing which
          strategies score well on individual axes, and not a shortlist to build from.
        </Caveat>
      )}

      <Panel
        title="Reaction graph"
        subtitle="compartment is colour, because a force layout cannot honestly draw it as position"
      >
        {graph.isLoading ? (
          <Loading what="the reaction graph" />
        ) : graph.error ? (
          <ErrorBox error={graph.error} />
        ) : graph.data!.nodes.length === 0 ? (
          <Empty>no reactions are curated yet</Empty>
        ) : (
          <ReactionGraphView data={graph.data!} />
        )}
        {graph.data && graph.data.competing_reactions.length > 0 && (
          <p className="mt-3 text-[11px] text-amber-300/80">
            {graph.data.competing_reactions.length} reaction(s) are marked as competing — they
            draw flux away from the target product.
          </p>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Routes by cofactor strategy" subtitle="the five enumerated strategies">
          <BarList
            data={Object.entries(data.routes_by_strategy).sort((a, b) => b[1] - a[1])}
            onSelect={(key) => setStrategy(key === strategy ? undefined : key)}
          />
        </Panel>
        <Panel title="Steps by compartment" subtitle="where the enumeration places each step">
          <BarList data={Object.entries(data.steps_by_compartment).sort((a, b) => b[1] - a[1])} />
        </Panel>
        <Panel title="Parts available" subtitle="per step role">
          <BarList data={Object.entries(data.parts_by_role).sort((a, b) => b[1] - a[1])} />
          <div className="mt-4">
            <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-600">
              Steps by genetic code
            </div>
            <BarList data={Object.entries(data.steps_by_encoding_genome).sort((a, b) => b[1] - a[1])} />
          </div>
        </Panel>
      </div>

      <Panel
        title="Routes"
        subtitle={`ranked on one named axis — no composite score is invented${strategy ? ` · ${strategy}` : ""}`}
        right={
          <div className="flex items-center gap-2">
            <select
              value={axis}
              onChange={(event) => setAxis(event.target.value)}
              className="rounded border border-zinc-700 bg-zinc-950 px-2 py-1 text-xs text-zinc-200 focus:border-sky-600 focus:outline-none"
            >
              {AXES.map((a) => (
                <option key={a} value={a} disabled={data.unscored_axes.includes(a)}>
                  {a.replace("score_", "")}
                  {data.unscored_axes.includes(a) ? " (never computed)" : ""}
                </option>
              ))}
            </select>
            {strategy && (
              <button
                onClick={() => setStrategy(undefined)}
                className="text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                clear
              </button>
            )}
          </div>
        }
      >
        {routes.isLoading ? (
          <Loading what="routes" />
        ) : routes.error ? (
          <ErrorBox error={routes.error} />
        ) : (
          <>
            <Table head={["Route", "Strategy", "Balance", ...AXES.map((a) => a.replace("score_", ""))]}>
              {routes.data!.rows.map((route) => (
                <Row key={route.id}>
                  <Cell>
                    <Link to={{ name: "route", id: route.id }} className="font-mono text-[11px]">
                      {route.id.replace("YAA:ROUTE:", "")}
                    </Link>
                  </Cell>
                  <Cell className="font-mono text-[11px] text-zinc-400">
                    {route.cofactor_strategy ?? "—"}
                  </Cell>
                  <Cell>
                    <span
                      className={`rounded px-1.5 py-0.5 text-[11px] ${
                        route.balance_status === "pass"
                          ? "bg-emerald-500/10 text-emerald-300"
                          : "bg-red-500/10 text-red-300"
                      }`}
                    >
                      {route.balance_status ?? "—"}
                    </span>
                  </Cell>
                  {AXES.map((a) => (
                    <Cell key={a}>
                      <Score value={route[a]} />
                    </Cell>
                  ))}
                </Row>
              ))}
            </Table>
            <p className="mt-3 text-[11px] text-zinc-500">
              Ordered by <code className="text-zinc-400">{routes.data!.ordered_by}</code>, descending.
              {routes.data!.truncated && " This is a page, not a total."}
            </p>
          </>
        )}
      </Panel>

      <Caveat tone="info">{data.note}</Caveat>
    </div>
  );
}
