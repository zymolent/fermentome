/**
 * The small shared vocabulary every page draws from: panels, stats, tables, states.
 *
 * Kept deliberately thin. A component library would be more than eleven pages need, and the
 * pages are more readable when the markup is visible in them rather than three files away.
 */

import type { ReactNode } from "react";

import { useLink, type Route } from "@/lib/router";

export function Panel({
  title,
  subtitle,
  right,
  children,
  className = "",
}: {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={`rounded-lg border border-zinc-800 bg-zinc-900/40 ${className}`}
    >
      {(title || right) && (
        <header className="flex items-start justify-between gap-4 border-b border-zinc-800 px-4 py-3">
          <div className="min-w-0">
            {title && <h2 className="text-sm font-semibold text-zinc-100">{title}</h2>}
            {subtitle && <p className="mt-0.5 text-xs text-zinc-500">{subtitle}</p>}
          </div>
          {right}
        </header>
      )}
      <div className="p-4">{children}</div>
    </section>
  );
}

/**
 * A single number with its label.
 *
 * `hint` exists so a count can carry what it excludes — "172 runs" next to "0 downloaded" is a
 * different claim from "172 runs" alone, and the hint is where that goes.
 */
export function Stat({
  label,
  value,
  hint,
  tone = "default",
  onClick,
}: {
  label: string;
  value: string | number;
  hint?: string;
  tone?: "default" | "warn" | "good" | "muted";
  onClick?: () => void;
}) {
  const toneClass = {
    default: "text-zinc-100",
    warn: "text-amber-300",
    good: "text-emerald-300",
    muted: "text-zinc-500",
  }[tone];
  const interactive = onClick ? "cursor-pointer hover:border-zinc-700 hover:bg-zinc-900" : "";
  return (
    <div
      onClick={onClick}
      className={`rounded-lg border border-zinc-800 bg-zinc-900/40 px-4 py-3 ${interactive}`}
    >
      <div className={`font-mono text-2xl tabular-nums ${toneClass}`}>
        {typeof value === "number" ? value.toLocaleString() : value}
      </div>
      <div className="mt-1 text-xs font-medium text-zinc-400">{label}</div>
      {hint && <div className="mt-1 text-[11px] leading-snug text-zinc-600">{hint}</div>}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{children}</div>;
}

export function Link({ to, children, className = "" }: { to: Route; children: ReactNode; className?: string }) {
  const props = useLink(to);
  return (
    <a
      {...props}
      className={`text-sky-400 underline-offset-2 hover:underline ${className}`}
    >
      {children}
    </a>
  );
}

export function PageHeader({
  title,
  lede,
  children,
}: {
  title: string;
  lede?: string;
  children?: ReactNode;
}) {
  return (
    <header className="mb-6">
      <h1 className="text-xl font-semibold tracking-tight text-zinc-50">{title}</h1>
      {lede && <p className="mt-1.5 max-w-3xl text-sm leading-relaxed text-zinc-400">{lede}</p>}
      {children && <div className="mt-4">{children}</div>}
    </header>
  );
}

export function Loading({ what = "the atlas" }: { what?: string }) {
  return <p className="animate-pulse text-sm text-zinc-500">Reading {what}…</p>;
}

/**
 * An error, with the server's own words.
 *
 * The API's 503 says which file it looked for and how to point it elsewhere; replacing that
 * with "something went wrong" would throw away the only actionable part.
 */
export function ErrorBox({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  return (
    <div className="rounded-lg border border-red-900/60 bg-red-950/30 p-4">
      <p className="text-sm font-medium text-red-300">Could not read the atlas</p>
      <p className="mt-1 font-mono text-xs leading-relaxed text-red-200/70">{message}</p>
      <p className="mt-2 text-xs text-zinc-500">
        Is the API running? <code className="text-zinc-400">just api</code>
      </p>
    </div>
  );
}

/** Nothing here — and, more usefully, why nothing is here. */
export function Empty({ children }: { children: ReactNode }) {
  return (
    <p className="rounded border border-dashed border-zinc-800 px-3 py-6 text-center text-sm text-zinc-500">
      {children}
    </p>
  );
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-zinc-800">
            {head.map((h) => (
              <th
                key={h}
                className="whitespace-nowrap px-3 py-2 text-left text-xs font-medium uppercase tracking-wide text-zinc-500"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

export function Row({ children }: { children: ReactNode }) {
  return <tr className="border-b border-zinc-900 hover:bg-zinc-900/50">{children}</tr>;
}

export function Cell({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <td className={`px-3 py-2 align-top text-zinc-300 ${className}`}>{children}</td>;
}

/**
 * A proportional bar chart made of divs.
 *
 * Categorical counts do not need a charting library, and one fewer dependency in the render
 * path is one fewer thing that can fail to load. ECharts is kept for the charts that earn it.
 */
export function BarList({
  data,
  total,
  onSelect,
  emptyLabel = "nothing recorded",
}: {
  data: [string, number][];
  total?: number;
  onSelect?: (key: string) => void;
  emptyLabel?: string;
}) {
  if (data.length === 0) return <Empty>{emptyLabel}</Empty>;
  const max = total ?? Math.max(...data.map(([, n]) => n));
  return (
    <ul className="space-y-1.5">
      {data.map(([key, n]) => (
        <li
          key={key}
          onClick={onSelect ? () => onSelect(key) : undefined}
          className={`group relative overflow-hidden rounded px-2 py-1.5 ${onSelect ? "cursor-pointer" : ""}`}
        >
          <div
            className="absolute inset-y-0 left-0 bg-sky-500/15 transition-all group-hover:bg-sky-500/25"
            style={{ width: `${max > 0 ? (n / max) * 100 : 0}%` }}
          />
          <div className="relative flex items-center justify-between gap-4">
            <span className="truncate text-xs text-zinc-300" title={key}>
              {key}
            </span>
            <span className="shrink-0 font-mono text-xs tabular-nums text-zinc-400">
              {n.toLocaleString()}
            </span>
          </div>
        </li>
      ))}
    </ul>
  );
}
