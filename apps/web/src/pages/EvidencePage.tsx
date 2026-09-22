/**
 * Evidence: every active assertion, and where its traceability chain breaks.
 *
 * PLAN.md P.2 for this page: "The J.5 chain rendered as a chain." So the hops are drawn as a
 * connected path — evidence item → measurement → span → publication — rather than as a table of
 * ids, because the thing a reader is checking is whether the path *reaches the source*, and a
 * table makes that a manual join.
 *
 * `vacuous` is the field that matters most and is easiest to miss: a walk over zero assertions
 * reports zero breaks, which renders as a perfect green score. The page refuses that reading.
 */

import { useQuery } from "@tanstack/react-query";
import { ChevronRight } from "lucide-react";

import { Caveat } from "@/components/Value";
import {
  BarList,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Panel,
  Stat,
  StatGrid,
} from "@/components/ui";
import { api } from "@/lib/api";

interface EvidenceChain {
  evidence_id: string;
  evidence_type: string;
  closes: boolean;
  arms: string[];
  hops: string[];
  breaks?: { kind: string; detail?: string }[];
}

interface AssertionChain {
  assertion_id: string;
  predicate: string;
  subject: string;
  object: string;
  zone: string;
  closes: boolean;
  evidence: EvidenceChain[];
  breaks?: { kind: string; detail?: string }[];
}

interface Walk {
  n_walked: number;
  n_closed: number;
  n_broken: number;
  vacuous: boolean;
  breaks_by_kind: Record<string, number>;
  gaps_by_kind: Record<string, number>;
  assertions: AssertionChain[];
}

/** The hops drawn as a path. Each hop is `kind id`; the kind leads because it is the shape. */
function Chain({ hops }: { hops: string[] }) {
  return (
    <ol className="flex flex-wrap items-center gap-1">
      {hops.map((hop, index) => {
        const [kind, ...rest] = hop.split(" ");
        const id = rest.join(" ");
        return (
          <li key={`${hop}-${index}`} className="flex items-center gap-1">
            <span className="rounded border border-zinc-800 bg-zinc-900/60 px-1.5 py-0.5">
              <span className="text-[10px] uppercase tracking-wide text-zinc-500">{kind}</span>
              <span className="ml-1.5 font-mono text-[10px] text-zinc-300">
                {id.length > 26 ? `${id.slice(0, 26)}…` : id}
              </span>
            </span>
            {index < hops.length - 1 && <ChevronRight className="h-3 w-3 shrink-0 text-zinc-700" />}
          </li>
        );
      })}
    </ol>
  );
}

export function EvidencePage() {
  const walk = useQuery({
    queryKey: ["assertions"],
    queryFn: () => api.assertions() as unknown as Promise<Walk>,
  });

  if (walk.isLoading) return <Loading what="the evidence chains" />;
  if (walk.error) return <ErrorBox error={walk.error} />;
  const data = walk.data as unknown as Walk;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Evidence"
        lede="Every active assertion, walked from the claim back to the sentence that supports it.
              An assertion closes when the walk reaches a source; it breaks when the path runs out
              partway. Both are shown, because a broken chain is a curation task, not an error."
      />

      <StatGrid>
        <Stat label="Assertions walked" value={data.n_walked} hint="active assertions only" />
        <Stat
          label="Chains that close"
          value={data.n_closed}
          tone={data.n_closed === data.n_walked && !data.vacuous ? "good" : "default"}
          hint="the walk reached a source"
        />
        <Stat
          label="Chains that break"
          value={data.n_broken}
          tone={data.n_broken > 0 ? "warn" : "default"}
          hint="the path ran out before a source"
        />
        <Stat
          label="Break kinds"
          value={Object.keys(data.breaks_by_kind).length}
          hint={Object.keys(data.breaks_by_kind).join(", ") || "no breaks recorded"}
        />
      </StatGrid>

      {data.vacuous && (
        <Caveat>
          This walk is <strong>vacuous</strong>: it covered no assertions, so "zero breaks" is not
          a passing result — it is the absence of anything to test. A green score here would be
          the same empty tick in a different costume.
        </Caveat>
      )}

      {Object.keys(data.breaks_by_kind).length > 0 && (
        <div className="grid gap-6 lg:grid-cols-2">
          <Panel title="Breaks by kind" subtitle="where chains stop">
            <BarList data={Object.entries(data.breaks_by_kind).sort((a, b) => b[1] - a[1])} />
          </Panel>
          <Panel title="Gaps by kind" subtitle="what is missing rather than broken">
            <BarList data={Object.entries(data.gaps_by_kind).sort((a, b) => b[1] - a[1])} />
          </Panel>
        </div>
      )}

      <Panel
        title="Assertions"
        subtitle="subject · predicate · object, each with its evidence chain"
      >
        {(data.assertions ?? []).length === 0 ? (
          <Empty>
            No active assertions. The atlas holds records, but nothing has yet been asserted from
            them — which is a different state from “nothing is true”.
          </Empty>
        ) : (
          <ul className="space-y-4">
            {data.assertions.map((assertion) => (
              <li
                key={assertion.assertion_id}
                className="rounded border border-zinc-800 bg-zinc-900/30 p-3"
              >
                <div className="flex flex-wrap items-baseline gap-2">
                  <span
                    className={`rounded px-1.5 py-0.5 text-[10px] ${
                      assertion.closes
                        ? "bg-emerald-500/10 text-emerald-300"
                        : "bg-red-500/10 text-red-300"
                    }`}
                  >
                    {assertion.closes ? "closes" : "breaks"}
                  </span>
                  <span className="font-mono text-xs text-zinc-300">{assertion.subject}</span>
                  <span className="text-xs font-medium text-sky-400">{assertion.predicate}</span>
                  <span className="font-mono text-xs text-zinc-300">{assertion.object}</span>
                  <span className="ml-auto font-mono text-[10px] text-zinc-600">
                    {assertion.assertion_id}
                  </span>
                </div>

                <div className="mt-3 space-y-2">
                  {assertion.evidence.map((evidence) => (
                    <div key={evidence.evidence_id} className="rounded bg-zinc-950/50 p-2.5">
                      <div className="mb-1.5 flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="text-zinc-400">{evidence.evidence_type}</span>
                        {evidence.arms.map((arm) => (
                          <span
                            key={arm}
                            className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400"
                          >
                            {arm}
                          </span>
                        ))}
                        {!evidence.closes && (
                          <span className="text-[10px] text-red-400">does not close</span>
                        )}
                      </div>
                      <Chain hops={evidence.hops} />
                    </div>
                  ))}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}
