/**
 * Curation: the proposal queue, read-only.
 *
 * There is no accept button here, and that is a design decision rather than an unfinished
 * feature. PLAN.md D.3 puts the interface above the query layer and names the violation to guard
 * against — the UI reaching past it — and the audit log records a *named human* as the actor for
 * every promotion. A browser click is not a named human.
 *
 * So the page does what a queue view can honestly do: show what is waiting, show the quote it
 * rests on, show what accepting would write, and print the exact `fermdb curate` command. The
 * person stays the actor.
 *
 * Every proposed field arrives in Zone I. They are rendered with the inferred badge because P.4
 * requires Zone I to be visually distinct everywhere — and a queue is precisely where a reader
 * is deciding whether to promote inference into fact.
 */

import { useQuery } from "@tanstack/react-query";
import { Copy } from "lucide-react";

import { Caveat, ValueView } from "@/components/Value";
import {
  Empty,
  ErrorBox,
  Link,
  Loading,
  PageHeader,
  Panel,
  Stat,
  StatGrid,
} from "@/components/ui";
import { api, type Value } from "@/lib/api";

interface Packet {
  task_id: string;
  record_kind: string;
  record_path: string;
  status: string;
  citation: { source_kind: string; source_id: string; locator?: string };
  fields: { name: string; value: Value<unknown> }[];
  model_confidence: Value<string>;
  // The span's quote fields are plain strings, not wrapped `Value`s — unlike the proposed
  // fields above them. Typing them as `Value` and calling `isKnown` on them is what took this
  // page down the first time it met real data.
  span: {
    status: string;
    resolves: boolean;
    detail: string;
    quote_as_recorded?: string;
    quote_in_source?: string;
    before?: string;
    after?: string;
  };
  plan?: string[];
  warnings: { severity?: string; message?: string; detail?: string }[];
  times_proposed: number;
  times_rejected: number;
  needs_attention: boolean;
}

function CopyButton({ text }: { text: string }) {
  return (
    <button
      onClick={() => void navigator.clipboard?.writeText(text)}
      title="copy to clipboard"
      className="inline-flex items-center gap-1 rounded border border-zinc-700 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:border-zinc-600 hover:text-zinc-200"
    >
      <Copy className="h-3 w-3" /> copy
    </button>
  );
}

export function CurationPage() {
  const queue = useQuery({
    queryKey: ["queue"],
    queryFn: () => api.curationQueue(15) as unknown as Promise<Packet[]>,
  });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });

  if (queue.isLoading) return <Loading what="the queue" />;
  if (queue.error) return <ErrorBox error={queue.error} />;
  const packets = queue.data as unknown as Packet[];

  const attention = packets.filter((p) => p.needs_attention).length;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Curation"
        lede="What is waiting for a decision. This page cannot make one: promotion is recorded against
              a named human in the audit log, and a browser click is not a named human. Each packet
              prints the command that would accept it."
      />

      <StatGrid>
        <Stat
          label="Pending, total"
          value={coverage.data?.pending_total ?? "…"}
          tone="warn"
          hint="across every record kind"
        />
        <Stat label="Shown here" value={packets.length} hint="the next in queue order" />
        <Stat
          label="Need attention"
          value={attention}
          tone={attention > 0 ? "warn" : "default"}
          hint="a warning, or a quote that no longer resolves"
        />
        <Stat
          label="Kinds queued"
          value={Object.keys(coverage.data?.pending_by_kind ?? {}).length}
          hint={Object.keys(coverage.data?.pending_by_kind ?? {}).slice(0, 3).join(", ")}
        />
      </StatGrid>

      <Caveat tone="info">
        Looking at the queue takes no lease — a listing that claimed tasks would strand one every
        time somebody checked. Review one at a time with{" "}
        <code className="text-zinc-300">fermdb query review</code>, or generate the full review
        page with <code className="text-zinc-300">fermdb query review --html review.html</code>.
      </Caveat>

      {packets.length === 0 ? (
        <Empty>the queue is empty</Empty>
      ) : (
        <div className="space-y-4">
          {packets.map((packet) => {
            const command = `fermdb curate accept --task ${packet.task_id} --curator YOUR_NAME`;
            return (
              <Panel
                key={packet.task_id}
                title={`${packet.record_kind} · ${packet.record_path}`}
                subtitle={`${packet.citation.source_kind} ${packet.citation.source_id}${
                  packet.citation.locator ? ` · ${packet.citation.locator}` : ""
                }`}
                right={
                  <div className="flex items-center gap-2">
                    {packet.needs_attention && (
                      <span className="rounded bg-amber-500/10 px-1.5 py-0.5 text-[10px] text-amber-300">
                        needs attention
                      </span>
                    )}
                    <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-[10px] text-zinc-400">
                      {packet.status}
                    </span>
                  </div>
                }
              >
                <div className="space-y-4">
                  {packet.span?.quote_in_source ? (
                    <div>
                      <div className="mb-1 text-[10px] uppercase tracking-wider text-zinc-600">
                        The sentence it rests on
                      </div>
                      <p
                        className={`rounded border px-3 py-2 font-serif text-sm leading-relaxed ${
                          packet.span.resolves
                            ? "border-zinc-800 bg-zinc-950/60 text-zinc-500"
                            : "border-amber-600/40 bg-amber-950/20 text-amber-100/90"
                        }`}
                      >
                        {packet.span.resolves && packet.span.before && (
                          <span>…{packet.span.before}</span>
                        )}
                        <mark className="rounded bg-sky-500/20 px-0.5 font-medium text-sky-100">
                          {packet.span.quote_in_source}
                        </mark>
                        {packet.span.resolves && packet.span.after && (
                          <span>{packet.span.after}…</span>
                        )}
                      </p>
                      <p className="mt-1 text-[10px] text-zinc-600">{packet.span.detail}</p>
                    </div>
                  ) : (
                    <Empty>no quote resolves for this proposal</Empty>
                  )}

                  <div>
                    <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-600">
                      What accepting would write
                    </div>
                    <dl className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
                      {packet.fields.map((field) => (
                        <div key={field.name} className="flex items-baseline gap-2">
                          <dt className="w-40 shrink-0 truncate font-mono text-[11px] text-zinc-500">
                            {field.name}
                          </dt>
                          <dd className="min-w-0 flex-1 truncate">
                            <ValueView v={field.value} />
                          </dd>
                        </div>
                      ))}
                    </dl>
                  </div>

                  {packet.warnings?.length > 0 && (
                    <ul className="space-y-1">
                      {packet.warnings.map((warning, index) => (
                        <li key={index} className="text-[11px] leading-snug text-amber-300/90">
                          ⚠ {warning.message ?? warning.detail ?? JSON.stringify(warning)}
                        </li>
                      ))}
                    </ul>
                  )}

                  <div className="flex flex-wrap items-center justify-between gap-2 border-t border-zinc-800 pt-3">
                    <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-zinc-500">
                      {command}
                    </code>
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] text-zinc-600">
                        proposed {packet.times_proposed}× · rejected {packet.times_rejected}×
                      </span>
                      <CopyButton text={command} />
                    </div>
                  </div>
                </div>
              </Panel>
            );
          })}
        </div>
      )}

      <p className="text-[11px] text-zinc-600">
        Reviewing many at once is faster in the generated review page than here — see{" "}
        <Link to={{ name: "dashboard" }}>the dashboard</Link> for what is queued by kind.
      </p>
    </div>
  );
}
