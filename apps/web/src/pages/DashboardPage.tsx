/**
 * The Dashboard.
 *
 * PLAN.md P.2 names the thing this page must get right: "Coverage, not just totals — *which*
 * conditions and products are thin is the actionable number." So the layout leads with the
 * empty tables grouped by *why* they are empty, and the totals come second.
 *
 * The three emptiness states are genuinely different work:
 *   - proposals queued → waiting on a curator, and the queue is reviewable today
 *   - accepted but unwritable → waiting on a promoter; the decision is already made
 *   - never populated → nobody has looked, which is a plan item, not a backlog item
 */

import { useQuery } from "@tanstack/react-query";

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
import { api, type EntityCoverage } from "@/lib/api";

const STATE_COPY: Record<string, { label: string; hint: string; tone: "warn" | "muted" | "good" }> = {
  actionable: {
    label: "Waiting on a curator",
    hint: "empty, but proposals are queued — reviewable today",
    tone: "warn",
  },
  awaiting_promoter: {
    label: "Waiting on a promoter",
    hint: "accepted and still unwritten — the decision is already made",
    tone: "warn",
  },
  never_populated: {
    label: "Never looked",
    hint: "empty with nothing proposed — a plan item, not a backlog item",
    tone: "muted",
  },
};

export function DashboardPage() {
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  const pages = useQuery({ queryKey: ["pages"], queryFn: api.pages });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });

  if (coverage.isLoading) return <Loading />;
  if (coverage.error) return <ErrorBox error={coverage.error} />;
  const data = coverage.data!;

  const entities = data.entities ?? [];
  const populated = entities.filter((e) => e.count > 0);
  const byState = (state: string) => entities.filter((e) => e.state === state);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        lede="What the atlas holds — and, the useful half, what it does not. An empty table is not a
              failure state; it is one of three different kinds of work, and they are separated below."
      />

      <StatGrid>
        <Stat
          label="Tables with content"
          value={`${populated.length} / ${entities.length}`}
          hint="entities carrying at least one row"
        />
        <Stat
          label="Proposals pending"
          value={data.pending_total ?? 0}
          tone={data.pending_total > 0 ? "warn" : "default"}
          hint="queued for a curator's decision"
        />
        <Stat
          label="P.2 pages renderable"
          value={
            pages.data ? `${pages.data.filter((p) => p.renderable).length} / ${pages.data.length}` : "…"
          }
          hint="pages with enough behind them to draw"
        />
        <Stat
          label="Atlas file"
          value={
            health.data?.size_bytes ? `${(health.data.size_bytes / 1e6).toFixed(0)} MB` : "…"
          }
          hint={health.data?.atlas ?? ""}
        />
      </StatGrid>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel
          title="Proposals pending, by kind"
          subtitle="the queue behind the number above — this is the work that is available today"
        >
          {data.pending_total === 0 ? (
            <Empty>nothing is queued</Empty>
          ) : (
            <BarList
              data={Object.entries(data.pending_by_kind)
                .filter(([, n]) => n > 0)
                .sort((a, b) => b[1] - a[1])}
              total={data.pending_total}
            />
          )}
        </Panel>

        {/* Only the states that actually apply. Three panels reading "nothing in this state" is
            noise; a state with no members is not a finding worth a panel of its own. */}
        {Object.entries(STATE_COPY).map(([state, copy]) => {
          const rows = byState(state);
          if (rows.length === 0) return null;
          return (
            <Panel key={state} title={copy.label} subtitle={copy.hint}>
              <BarList
                data={rows.map(
                  (e) => [e.label, e.pending || e.accepted_unpromotable || 0] as [string, number],
                )}
              />
            </Panel>
          );
        })}
      </div>

      <Panel
        title="What is in the atlas"
        subtitle="row counts by entity, largest first"
        right={
          <Link to={{ name: "curation" }} className="text-xs">
            review the queue →
          </Link>
        }
      >
        <Table head={["Entity", "Rows", "Queued", "State"]}>
          {[...populated]
            .sort((a, b) => b.count - a.count)
            .map((entity: EntityCoverage) => (
              <Row key={entity.label}>
                <Cell className="font-medium text-zinc-200">{entity.label}</Cell>
                <Cell className="font-mono tabular-nums">{entity.count.toLocaleString()}</Cell>
                <Cell className="font-mono tabular-nums text-zinc-500">
                  {entity.pending ? entity.pending.toLocaleString() : "—"}
                </Cell>
                <Cell className="text-xs text-zinc-500">{entity.state}</Cell>
              </Row>
            ))}
        </Table>
      </Panel>

      {pages.data && (
        <Panel title="P.2 pages" subtitle="which designed pages have content behind them">
          <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
            {pages.data.map((page) => (
              <div
                key={page.page}
                className="flex items-start gap-2 rounded border border-zinc-800 px-3 py-2"
              >
                <span
                  className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${
                    page.renderable ? "bg-emerald-400" : "bg-zinc-600"
                  }`}
                />
                <div className="min-w-0">
                  <div className="text-sm text-zinc-200">{page.page}</div>
                  <div className="text-[11px] leading-snug text-zinc-500">{page.note}</div>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <Caveat tone="info">
        Every number on this page is a count of rows, not a claim about the world. A populated
        table means the atlas holds records; whether those records support a conclusion is what
        the <Link to={{ name: "evidence" }}>Evidence</Link> page answers.
      </Caveat>
    </div>
  );
}
