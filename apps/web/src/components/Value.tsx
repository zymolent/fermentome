/**
 * Rendering `Value`s, which is PLAN.md P.4 expressed as components.
 *
 * P.4 says: "'Not recorded' and 'not applicable' render differently from each other and from
 * zero. These are not styling preferences — they are the user-facing expression of the whole
 * evidence architecture, and getting them wrong discards the value of everything underneath."
 *
 * So the three absences get three different treatments and none of them looks like a number:
 *
 * - **not recorded** — dashed, muted. The source never said.
 * - **not applicable** — struck through, muted. The source said it does not apply.
 * - **unknown** — dotted, amber. Recorded, but unresolvable to a controlled value; this is the
 *   one a curator can actually fix, so it is the one that draws the eye.
 *
 * Zone rides along as a badge because Zone I content must be visually distinct and explicitly
 * labelled *everywhere*, including in a table cell nobody thought about.
 */

import type { ReactNode } from "react";

import { isKnown, type Quantity, type Value, type Zone } from "@/lib/api";

const ZONE_STYLE: Record<Zone, string> = {
  R: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  H: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  I: "bg-amber-500/10 text-amber-300 ring-amber-500/30",
};

const ZONE_TITLE: Record<Zone, string> = {
  R: "Zone R — reported: as the source stated it",
  H: "Zone H — harmonized: derived by conversion or mapping, rebuildable",
  I: "Zone I — inferred: model output, may not support a conclusion until a curator promotes it",
};

export function ZoneBadge({ zone }: { zone?: Zone }) {
  if (!zone) return null;
  return (
    <span
      title={ZONE_TITLE[zone]}
      className={`ml-1.5 inline-flex h-4 items-center rounded px-1 font-mono text-[10px] font-semibold uppercase ring-1 ring-inset ${ZONE_STYLE[zone]}`}
    >
      {zone}
    </span>
  );
}

/** An absence, styled by *which* absence it is. Never renders as a number or a blank. */
export function Absent({ v }: { v: { display: string; absent: string; absent_because: string } }) {
  const style =
    v.absent === "not_applicable"
      ? "text-zinc-500 line-through decoration-zinc-600"
      : v.absent === "unknown"
        ? "text-amber-400/80 underline decoration-dotted decoration-amber-500/50 underline-offset-2"
        : "text-zinc-500 underline decoration-dashed decoration-zinc-600 underline-offset-2";
  return (
    <span className={`text-sm italic ${style}`} title={v.absent_because}>
      {v.display}
    </span>
  );
}

export function ValueView<T>({
  v,
  mono = false,
  showZone = true,
}: {
  v: Value<T> | null | undefined;
  mono?: boolean;
  showZone?: boolean;
}) {
  if (!v) return <Absent v={{ display: "not recorded", absent: "not_recorded", absent_because: "no value was supplied" }} />;
  if (!isKnown(v)) return <Absent v={v} />;
  return (
    <span className={mono ? "font-mono text-sm text-zinc-100" : "text-sm text-zinc-100"}>
      {v.display}
      {showZone && <ZoneBadge zone={v.zone} />}
    </span>
  );
}

/**
 * A quantity, showing the reported form with the harmonized one available on hover.
 *
 * Both travel because they are different claims in different zones: "2.09 g/L as the paper
 * wrote it" and "2.09 g/L after our conversion". The reported form leads, because that is what
 * the source actually said.
 */
export function QuantityView({ q }: { q: Quantity }) {
  const si = isKnown(q.si) ? `${q.si.value} ${isKnown(q.unit_si) ? q.unit_si.value : ""}`.trim() : null;
  return (
    <span
      className="font-mono text-sm text-zinc-100"
      title={si ? `harmonized (Zone H): ${si}` : "no harmonized form recorded"}
    >
      {q.display}
      {q.is_below_lod && (
        <span className="ml-1 text-[10px] uppercase text-amber-400" title="below limit of detection">
          lod
        </span>
      )}
      {si && <span className="ml-1.5 text-[10px] text-sky-400/70">H</span>}
    </span>
  );
}

/** A labelled row in a definition list. The label never wraps away from its value. */
export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-baseline gap-3 py-1.5">
      <dt className="w-44 shrink-0 text-xs uppercase tracking-wide text-zinc-500">{label}</dt>
      <dd className="min-w-0 flex-1 break-words">{children}</dd>
    </div>
  );
}

/**
 * A caveat the data itself carries.
 *
 * Deliberately not a tooltip. These strings come from the query layer — "no sample, so no
 * comparability class", "score_toxicity was never computed" — and they are the difference
 * between a number and a number you can act on. A tooltip hides them from anyone skimming.
 */
export function Caveat({ children, tone = "warn" }: { children: ReactNode; tone?: "warn" | "info" }) {
  const style =
    tone === "warn"
      ? "border-amber-500/30 bg-amber-500/5 text-amber-200/90"
      : "border-sky-500/30 bg-sky-500/5 text-sky-200/90";
  return (
    <p className={`rounded border px-3 py-2 text-xs leading-relaxed ${style}`}>{children}</p>
  );
}
