/**
 * Compare: two or more strains or experiments side by side, or a stated refusal to.
 *
 * PLAN.md P.2 gives this page one job — "Refuses or warns when the comparability class differs" —
 * and PLAN.md I.2 makes refusal a valid answer rather than a failure. So the verdict is the
 * loudest thing on the page, above the table, and the three verdicts look different:
 *
 * - **comparable** (emerald) — every subject is in the same classified comparability class.
 * - **warn** (amber) — the numbers are shown, with the differing facets named above them. A
 *   comparison across classes is offered, never silently.
 * - **refuse** (red) — the aligned metric table is *not rendered at all*. The subjects' own
 *   attributes still are, because organism, strain class and genotype are properties of the
 *   subject rather than of the conditions it was measured under, and comparing those needs no
 *   class. What a refusal withholds is only the thing that would be misread.
 *
 * Against the atlas as it stands, every strain comparison refuses: no measurement carries a
 * `sample_id`, so nothing reaches a condition context and nothing has a class. The page is
 * therefore mostly an exercise of its refusal path, which is the correct outcome and not a bug.
 */

import { useQuery } from "@tanstack/react-query";
import { Check, Plus, TriangleAlert, X } from "lucide-react";

import { Caveat } from "@/components/Value";
import { ValueView } from "@/components/Value";
import {
  Cell,
  Empty,
  ErrorBox,
  Link,
  Loading,
  PageHeader,
  Panel,
  Row,
  Table,
} from "@/components/ui";
import { api, isKnown, type Comparison, type Verdict } from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

const VERDICT: Record<Verdict, { label: string; style: string; icon: typeof Check }> = {
  comparable: {
    label: "comparable",
    style: "border-emerald-700/50 bg-emerald-950/30 text-emerald-200",
    icon: Check,
  },
  warn: {
    label: "comparable with a warning",
    style: "border-amber-600/50 bg-amber-950/25 text-amber-100",
    icon: TriangleAlert,
  },
  refuse: {
    label: "comparison refused",
    style: "border-red-900/60 bg-red-950/30 text-red-100",
    icon: X,
  },
};

function VerdictBanner({ comparison }: { comparison: Comparison }) {
  const verdict = VERDICT[comparison.verdict];
  const Icon = verdict.icon;
  return (
    <div className={`rounded-lg border p-4 ${verdict.style}`}>
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 h-4 w-4 shrink-0" />
        <div className="min-w-0 space-y-1.5">
          <p className="text-sm font-semibold uppercase tracking-wide">{verdict.label}</p>
          <p className="text-xs leading-relaxed opacity-90">{comparison.reason}</p>
          {comparison.differing_facets.length > 0 && (
            <p className="text-xs opacity-80">
              facets that differ: {comparison.differing_facets.join(", ")}
            </p>
          )}
          {comparison.warnings.map((warning, index) => (
            <p key={index} className="text-[11px] leading-relaxed opacity-80">
              · {warning}
            </p>
          ))}
        </div>
      </div>
    </div>
  );
}

/** The picker. Kept on the page rather than in a modal so the URL is always the whole state. */
function SubjectPicker({ route }: { route: Extract<Route, { name: "compare" }> }) {
  const candidates = useQuery({
    queryKey: ["compare-candidates", route.kind],
    queryFn: () => api.compareCandidates(route.kind),
  });

  const toggle = (id: string) =>
    navigate({
      name: "compare",
      kind: route.kind,
      ids: route.ids.includes(id) ? route.ids.filter((other) => other !== id) : [...route.ids, id],
    });

  return (
    <Panel
      title="Subjects"
      subtitle="most-populated first — an ordering over the atlas, not over the science"
      right={
        <div className="flex gap-1">
          {(["strain", "experiment"] as const).map((kind) => (
            <button
              key={kind}
              onClick={() => navigate({ name: "compare", kind, ids: [] })}
              className={`rounded px-2 py-0.5 text-[11px] ${
                route.kind === kind
                  ? "bg-sky-500/15 text-sky-300"
                  : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {kind}s
            </button>
          ))}
        </div>
      }
    >
      {candidates.isLoading ? (
        <Loading what="candidates" />
      ) : candidates.error ? (
        <ErrorBox error={candidates.error} />
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {candidates.data!.slice(0, 40).map((candidate) => {
            const selected = route.ids.includes(candidate.id);
            return (
              <button
                key={candidate.id}
                onClick={() => toggle(candidate.id)}
                title={`${candidate.weight} measurement(s) or sample(s) recorded`}
                className={`inline-flex items-center gap-1 rounded border px-2 py-1 text-xs ${
                  selected
                    ? "border-sky-600/60 bg-sky-500/15 text-sky-200"
                    : "border-zinc-800 text-zinc-400 hover:border-zinc-700 hover:text-zinc-200"
                }`}
              >
                {selected ? <Check className="h-3 w-3" /> : <Plus className="h-3 w-3" />}
                {candidate.label}
                <span className="font-mono text-[10px] text-zinc-600">{candidate.weight}</span>
              </button>
            );
          })}
        </div>
      )}
    </Panel>
  );
}

export function ComparePage({ route }: { route: Extract<Route, { name: "compare" }> }) {
  const comparison = useQuery({
    queryKey: ["compare", route.kind, route.ids],
    queryFn: () => api.compare(route.kind, route.ids),
    enabled: route.ids.length > 0,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Compare"
        lede="Two or more strains or experiments side by side. A comparison is offered only inside
              a comparability class, or with the facets that differ named — and refused outright
              when no subject has a class at all. Refusal is an answer here, not a failure."
      />

      <SubjectPicker route={route} />

      {route.ids.length === 0 ? (
        <Empty>pick at least two subjects above</Empty>
      ) : comparison.isLoading ? (
        <Loading what="the comparison" />
      ) : comparison.error ? (
        <ErrorBox error={comparison.error} />
      ) : (
        <ComparisonView comparison={comparison.data!} kind={route.kind} />
      )}
    </div>
  );
}

function ComparisonView({ comparison, kind }: { comparison: Comparison; kind: string }) {
  const { subjects } = comparison;
  const differing = comparison.differences.filter((difference) => difference.differs);

  return (
    <div className="space-y-6">
      <VerdictBanner comparison={comparison} />

      {subjects.length === 0 ? (
        <Empty>nothing to compare</Empty>
      ) : (
        <>
          <Panel title="Side by side" subtitle="properties of the subject, not of its conditions">
            <Table head={["", ...subjects.map((subject) => subject.label)]}>
              {(subjects[0]?.attributes ?? []).map((attribute, index) => (
                <Row key={attribute.label}>
                  <Cell className="whitespace-nowrap text-xs uppercase tracking-wide text-zinc-500">
                    {attribute.label}
                  </Cell>
                  {subjects.map((subject) => (
                    <Cell key={subject.id} className="max-w-xs">
                      <ValueView v={subject.attributes[index]?.value} showZone={false} />
                    </Cell>
                  ))}
                </Row>
              ))}
              <Row>
                <Cell className="whitespace-nowrap text-xs uppercase tracking-wide text-zinc-500">
                  open
                </Cell>
                {subjects.map((subject) => (
                  <Cell key={subject.id}>
                    <Link
                      to={
                        kind === "strain"
                          ? { name: "strain", id: subject.id }
                          : { name: "experiment", id: subject.id }
                      }
                      className="text-xs"
                    >
                      {subject.label}
                    </Link>
                  </Cell>
                ))}
              </Row>
            </Table>
          </Panel>

          {differing.length > 0 && (
            <Panel
              title="Condition facets"
              subtitle="only the facets on which the subjects differ; class-defining ones are marked"
            >
              <Table head={["Facet", ...subjects.map((subject) => subject.label), "Verdict"]}>
                {differing.map((difference) => (
                  <Row key={difference.facet}>
                    <Cell className="whitespace-nowrap text-xs">
                      <span
                        className={
                          difference.is_class_defining ? "text-sky-300" : "text-zinc-400"
                        }
                      >
                        {difference.label}
                      </span>
                      {difference.tolerance && (
                        <span className="ml-1.5 text-[10px] text-zinc-600">
                          {difference.tolerance}
                        </span>
                      )}
                    </Cell>
                    {difference.values.map((value, index) => (
                      <Cell key={index} className="text-xs text-zinc-300">
                        {value}
                      </Cell>
                    ))}
                    <Cell className="text-[11px]">
                      {difference.within_tolerance ? (
                        <span className="text-emerald-400/80">within tolerance</span>
                      ) : difference.is_class_defining ? (
                        <span className="text-red-400">class-defining — differs</span>
                      ) : (
                        <span className="text-amber-400/80">differs</span>
                      )}
                    </Cell>
                  </Row>
                ))}
              </Table>
            </Panel>
          )}

          <Panel
            title="Metrics"
            subtitle={
              comparison.verdict === "refuse"
                ? "not shown — see the refusal above"
                : "one row per quantity kind and unit; a unit is never shared across a row"
            }
          >
            {comparison.verdict === "refuse" ? (
              <div className="space-y-3">
                <Empty>
                  The numbers are deliberately not aligned into a comparison here. Each subject&apos;s
                  own measurements remain on its page, where they carry the conditions they were
                  measured under.
                </Empty>
                <Caveat>{comparison.reason}</Caveat>
              </div>
            ) : comparison.metrics.length === 0 ? (
              <Empty>no measurement is recorded for any of these subjects</Empty>
            ) : (
              <Table head={["Quantity", "Unit", ...subjects.map((subject) => subject.label)]}>
                {comparison.metrics.map((metric) => (
                  <Row key={`${metric.quantity_kind}-${metric.unit}`}>
                    <Cell className="text-xs">
                      <span
                        className={
                          metric.is_controlled_kind ? "text-zinc-300" : "text-amber-300/80"
                        }
                      >
                        {metric.quantity_kind.length > 34
                          ? `${metric.quantity_kind.slice(0, 34)}…`
                          : metric.quantity_kind}
                      </span>
                    </Cell>
                    <Cell className="font-mono text-[11px] text-zinc-500">{metric.unit}</Cell>
                    {metric.values.map((value, index) => (
                      <Cell key={index}>
                        {value === null ? (
                          // A subject that has no such number: an absence, never a blank or a 0.
                          <span className="text-sm italic text-zinc-500 underline decoration-dashed decoration-zinc-600 underline-offset-2">
                            not recorded
                          </span>
                        ) : (
                          <span className="font-mono text-sm text-zinc-100">
                            {value.quantity.display}
                          </span>
                        )}
                      </Cell>
                    ))}
                  </Row>
                ))}
              </Table>
            )}
          </Panel>

          <Panel title="Comparability" subtitle="how each subject's class was arrived at">
            <ul className="space-y-3">
              {subjects.map((subject) => (
                <li key={subject.id} className="space-y-1">
                  <div className="text-xs font-medium text-zinc-200">{subject.label}</div>
                  <p className="text-[11px] leading-relaxed text-zinc-500">
                    {subject.context_note}
                  </p>
                  {subject.classes.map((klass) => (
                    <p key={klass.key} className="text-[11px] text-zinc-600">
                      {klass.status}
                      {isKnown(klass.context_id) && ` · ${klass.context_id.value}`}
                      {klass.blocked_by.length > 0 && ` — ${klass.blocked_by[0]}`}
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          </Panel>
        </>
      )}
    </div>
  );
}
