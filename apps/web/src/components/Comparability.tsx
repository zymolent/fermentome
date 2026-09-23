/**
 * Rendering a comparability class and a condition context — PLAN.md K.4 and I.2 as components.
 *
 * Four pages need these and all four must draw them identically, because the distinction they
 * carry is the one the atlas exists to protect: a titer is a statement about a strain *under
 * conditions*, and two numbers are comparable only inside a class.
 *
 * `status` is three-valued and each value gets its own colour, deliberately:
 *
 * - **classified** — every class-defining facet was readable. Comparison is offered.
 * - **provisional** — amber. The class key is blind to a facet that has no column in the schema,
 *   so two contexts can share the key and still differ. Comparison is offered *with* the warning.
 * - **unclassified** — zinc, and never green. No comparison is offered at all.
 *
 * The middle one is the one that would be lost by a boolean, and it is the one that matters:
 * "these look the same to the key" is a weaker claim than "these are the same", and a reader
 * cannot tell the two apart unless the interface says which it is.
 */

import type { ReactNode } from "react";

import { Absent, ValueView } from "@/components/Value";
import { Cell, Empty, Panel, Row, Table } from "@/components/ui";
import { isKnown, type ComparabilityClass, type ConditionContext } from "@/lib/api";

const STATUS_STYLE: Record<string, string> = {
  classified: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  provisional: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
  unclassified: "bg-zinc-800/60 text-zinc-400 ring-zinc-700",
};

export function ClassBadge({ klass }: { klass: ComparabilityClass }) {
  return (
    <span
      title={klass.definition_source}
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${
        STATUS_STYLE[klass.status] ?? STATUS_STYLE.unclassified
      }`}
    >
      {klass.status}
    </span>
  );
}

/**
 * The class header: what it is, and every reason it is not more than that.
 *
 * `blocked_by` and `blind_to` are rendered as lists rather than folded into one sentence
 * because they are different failures — one is a curator's missing entry, the other is a column
 * the schema never got — and they have different remedies.
 */
export function ClassHeader({ klass, right }: { klass: ComparabilityClass; right?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <ClassBadge klass={klass} />
          <span className="text-sm text-zinc-200">{klass.label}</span>
          {isKnown(klass.context_id) && (
            <span className="font-mono text-[10px] text-zinc-600">
              {klass.context_id.value.replace("YAA:CCTX:", "ctx ")}
            </span>
          )}
        </div>
        {klass.blocked_by.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {klass.blocked_by.map((reason, index) => (
              <li key={index} className="text-[11px] leading-snug text-zinc-500">
                · {reason}
              </li>
            ))}
          </ul>
        )}
        {klass.blind_to.length > 0 && (
          <ul className="mt-1.5 space-y-0.5">
            {klass.blind_to.map((reason, index) => (
              <li key={index} className="text-[11px] leading-snug text-amber-400/70">
                blind to: {reason}
              </li>
            ))}
          </ul>
        )}
      </div>
      {right}
    </div>
  );
}

/**
 * Every facet of a condition context, recorded or not.
 *
 * This is PLAN.md P.2's brief for the Experiment page — "the condition context in full, with
 * 'not recorded' visible" — and the reason no row is filtered out. A table of the three facets
 * somebody happened to fill in looks like a complete record of a well-described experiment.
 * Nineteen rows of which eighteen say "not recorded" looks like what it is.
 */
export function ContextTable({ context }: { context: ConditionContext }) {
  const absent = context.absent_by_kind;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-zinc-500">
        <span className="font-mono text-zinc-400">{context.id.replace("YAA:CCTX:", "")}</span>
        <span>
          <span className="text-zinc-300">{context.recorded}</span> of {context.total_facets} facets
          recorded
        </span>
        {/* The three absences are counted separately and never added together. */}
        {(["not_recorded", "not_applicable", "unknown"] as const).map((kind) =>
          absent[kind] ? (
            <span key={kind}>
              {absent[kind]} {kind.replace("_", " ")}
            </span>
          ) : null,
        )}
        {isKnown(context.completeness_score) && (
          <span title="the atlas's own completeness score for this context">
            completeness {(context.completeness_score.value * 100).toFixed(0)}%
          </span>
        )}
      </div>

      <Table head={["Facet", "Value", "As reported"]}>
        {context.facets.map((facet) => (
          <Row key={facet.facet}>
            <Cell className="whitespace-nowrap text-xs">
              <span className={facet.is_class_defining ? "text-sky-300" : "text-zinc-400"}>
                {facet.label}
              </span>
              {facet.unit && <span className="ml-1 text-[10px] text-zinc-600">{facet.unit}</span>}
            </Cell>
            <Cell>
              <ValueView v={facet.value} />
            </Cell>
            <Cell className="max-w-sm">
              <ValueView v={facet.as_reported} showZone={false} />
            </Cell>
          </Row>
        ))}
        {context.extra_facets.map((facet) => (
          <Row key={`extra-${facet.facet}`}>
            <Cell className="whitespace-nowrap text-xs text-zinc-400">
              {facet.label}
              <span className="ml-1 text-[10px] text-zinc-600">extra</span>
            </Cell>
            <Cell>
              <ValueView v={facet.value} />
            </Cell>
            <Cell className="max-w-sm">
              <ValueView v={facet.as_reported} showZone={false} />
            </Cell>
          </Row>
        ))}
      </Table>

      {Object.entries(context.unavailable_class_facets).length > 0 && (
        <div className="rounded border border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-amber-400/80">
            class-defining facets with nowhere to live
          </div>
          <ul className="mt-1 space-y-1">
            {Object.entries(context.unavailable_class_facets).map(([facet, why]) => (
              <li key={facet} className="text-[11px] leading-relaxed text-amber-200/70">
                <span className="font-mono">{facet}</span> — {why}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** A context panel, or an explicit statement that there is no context — never a blank card. */
export function ContextPanel({
  contexts,
  note,
}: {
  contexts: ConditionContext[];
  note: string;
}) {
  return (
    <Panel title="Condition context" subtitle={note}>
      {contexts.length === 0 ? (
        <Empty>{note}</Empty>
      ) : (
        <div className="space-y-8">
          {contexts.map((context) => (
            <div key={context.id} className="space-y-3">
              <ClassHeader klass={context.comparability_class} />
              <ContextTable context={context} />
            </div>
          ))}
        </div>
      )}
    </Panel>
  );
}

/** A value that is absent because nothing was recorded, for a caller with no `Value` to hand. */
export function NotRecorded({ why }: { why: string }) {
  return <Absent v={{ display: "not recorded", absent: "not_recorded", absent_because: why }} />;
}
