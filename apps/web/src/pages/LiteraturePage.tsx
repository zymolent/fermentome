/**
 * Literature: the corpus funnel, then the papers themselves.
 *
 * The funnel is the point of the page. Each stage carries a `remedy` from the query layer, and
 * the remedy is what makes the number actionable — "1,033 excluded" is trivia, "1,033 excluded,
 * re-screening reverses this without new acquisition" is a piece of work.
 *
 * Stages are drawn as a list rather than a funnel chart on purpose: the stages are not nested
 * subsets of one another (a paper can be both `needs_full_text` and included under a different
 * family), and a funnel chart would assert a containment that does not hold.
 */

import { useState } from "react";
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
import { api } from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

export function LiteraturePage({ route }: { route: Extract<Route, { name: "literature" }> }) {
  const [query, setQuery] = useState(route.q ?? "");
  const overview = useQuery({ queryKey: ["lit-overview"], queryFn: api.literatureOverview });
  const families = useQuery({ queryKey: ["lit-families"], queryFn: api.literatureFamilies });
  const publications = useQuery({
    queryKey: ["publications", route.q, route.family, route.readable],
    queryFn: () =>
      api.publications({
        q: route.q,
        family: route.family,
        readable_only: route.readable,
        limit: 50,
      }),
  });

  if (overview.isLoading) return <Loading what="the corpus" />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const data = overview.data!;

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    navigate({ name: "literature", q: query || undefined, family: route.family, readable: route.readable });
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Literature"
        lede="A corpus narrows in three different ways, and each one has a different remedy. Papers
              never screened need a classifier run; papers excluded need a rubric change; papers
              wanted but unreadable need acquisition. They are separated here because treating them
              as one number hides which work is actually available."
      />

      <StatGrid>
        <Stat label="Publications known" value={data.publications} hint="a title and an identifier, at minimum" />
        <Stat
          label="Full text held"
          value={data.acquisition.readable}
          tone="good"
          hint="on disk and extractable"
        />
        <Stat
          label="Awaiting a verdict"
          value={data.publications - data.screened + (data.screened - Object.values(data.by_decision).reduce((a, b) => a + b, 0))}
          tone="warn"
          hint="screened with no decision recorded"
        />
        <Stat
          label="Manual download queue"
          value={data.acquisition.manual_queue}
          tone="warn"
          hint="publishers that will not serve an automated fetch"
        />
      </StatGrid>

      <Panel title="The funnel" subtitle="each stage, and what would widen it again">
        <ul className="space-y-2">
          {data.stages.map((stage) => {
            const share = data.publications > 0 ? (stage.count / data.publications) * 100 : 0;
            return (
              <li key={stage.key} className="relative overflow-hidden rounded border border-zinc-800 px-3 py-2.5">
                <div
                  className="absolute inset-y-0 left-0 bg-sky-500/10"
                  style={{ width: `${Math.min(100, share)}%` }}
                />
                <div className="relative">
                  <div className="flex items-baseline justify-between gap-4">
                    <span className="text-sm font-medium text-zinc-200">{stage.label}</span>
                    <span className="shrink-0 font-mono text-sm tabular-nums text-zinc-100">
                      {stage.count.toLocaleString()}
                      <span className="ml-2 text-[11px] text-zinc-500">{share.toFixed(0)}%</span>
                    </span>
                  </div>
                  <p className="mt-0.5 text-[11px] text-zinc-500">{stage.note}</p>
                  {stage.remedy && (
                    <p className="mt-1 text-[11px] font-medium text-amber-300/90">→ {stage.remedy}</p>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </Panel>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="By screening family" subtitle="a paper can sit in several">
          <BarList
            data={Object.entries(data.by_family).sort((a, b) => b[1] - a[1])}
            onSelect={(family) => navigate({ name: "literature", family, q: route.q })}
          />
        </Panel>
        <Panel title="Who decided" subtitle={data.decider_note}>
          <BarList data={Object.entries(data.by_decider_kind).sort((a, b) => b[1] - a[1])} />
          <div className="mt-4">
            <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-600">Verdicts</div>
            <BarList data={Object.entries(data.by_decision).sort((a, b) => b[1] - a[1])} />
          </div>
        </Panel>
        <Panel title="Acquisition" subtitle="what is actually on disk">
          <BarList data={Object.entries(data.acquisition.by_storage_state).sort((a, b) => b[1] - a[1])} />
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
            {data.acquisition.note}
          </p>
        </Panel>
      </div>

      <Panel
        title="Papers"
        subtitle={
          route.family
            ? `family: ${route.family}`
            : route.readable
              ? "full text held only"
              : "every publication, newest first"
        }
        right={
          <form onSubmit={submit} className="flex items-center gap-2">
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="title contains…"
              className="w-56 rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-sky-600 focus:outline-none"
            />
            <button
              type="button"
              onClick={() =>
                navigate({ name: "literature", q: route.q, family: route.family, readable: !route.readable })
              }
              className={`rounded border px-2 py-1 text-[11px] ${
                route.readable
                  ? "border-sky-600 bg-sky-500/10 text-sky-300"
                  : "border-zinc-700 text-zinc-400 hover:text-zinc-200"
              }`}
            >
              readable only
            </button>
            {(route.q || route.family || route.readable) && (
              <button
                type="button"
                onClick={() => {
                  setQuery("");
                  navigate({ name: "literature" });
                }}
                className="text-[11px] text-zinc-500 hover:text-zinc-300"
              >
                clear
              </button>
            )}
          </form>
        }
      >
        {publications.isLoading ? (
          <Loading what="papers" />
        ) : publications.error ? (
          <ErrorBox error={publications.error} />
        ) : publications.data!.rows.length === 0 ? (
          <Empty>no publication matches these filters</Empty>
        ) : (
          <>
            <Table head={["Year", "Title", "Journal", "DOI"]}>
              {publications.data!.rows.map((row) => (
                <Row key={row.id}>
                  <Cell className="font-mono text-xs text-zinc-500">{row.year ?? "—"}</Cell>
                  <Cell>
                    <Link to={{ name: "publication", id: row.id }}>{row.title ?? row.id}</Link>
                  </Cell>
                  <Cell className="text-xs text-zinc-500">{row.journal ?? "—"}</Cell>
                  <Cell className="font-mono text-[11px] text-zinc-600">{row.doi ?? "—"}</Cell>
                </Row>
              ))}
            </Table>
            {publications.data!.truncated && (
              <p className="mt-3 text-[11px] text-zinc-500">
                {publications.data!.note ?? "this is a page, not a total"}
              </p>
            )}
          </>
        )}
      </Panel>

      {families.data && families.data.length > 0 && (
        <Caveat tone="info">
          Screening families are separate questions asked of the same corpus, not a partition of
          it — {families.data.length} families over {data.publications.toLocaleString()} papers,
          and a paper admitted under one may be excluded under another.
        </Caveat>
      )}
    </div>
  );
}
