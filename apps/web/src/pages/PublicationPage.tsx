/**
 * One publication, with every extracted finding shown inside the sentence it came from.
 *
 * PLAN.md P.2 names the thing this page must get right: "Extraction provenance — click a value,
 * see the sentence." The atlas stores `before`, the quote, and `after` around a character
 * offset, so the sentence can be rebuilt exactly as it appeared rather than paraphrased.
 *
 * `resolves` is the field that decides how a finding is drawn. It is the answer to "does this
 * quote still appear in the stored full text?" — and a finding whose quote no longer resolves is
 * not a finding, it is a claim about a document that has since changed. Those are marked, not
 * hidden, because a silently dropped finding is indistinguishable from one that was never
 * extracted.
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { Caveat, Field, ValueView } from "@/components/Value";
import { Empty, ErrorBox, Link, Loading, Panel } from "@/components/ui";
import { api, isKnown, type Value } from "@/lib/api";

interface Finding {
  record_path: Value<string>;
  record_kind: Value<string>;
  task_status: Value<string>;
  section: Value<string>;
  quote_as_recorded: Value<string>;
  quote_in_source: Value<string>;
  resolves: boolean;
  is_established: boolean;
  before?: string;
  after?: string;
  char_start?: number;
}

interface Screening {
  family: string;
  triage_state: string;
  product_tier: string;
  admitted_criterion: Value<string>;
  exclusion_reason: Value<string>;
}

interface PublicationDetail {
  id: string;
  title: Value<string>;
  year: Value<number>;
  journal: Value<string>;
  doi: Value<string>;
  pmid: Value<string>;
  license: Value<string>;
  fulltext: {
    state: string;
    display: string;
    is_readable: boolean;
    media_type: Value<string>;
    oa_status: Value<string>;
    license: Value<string>;
    characters: Value<number>;
  };
  screening: Screening[];
  findings: Finding[];
  findings_truncated?: boolean;
}

/** The quote in its own sentence, with the surrounding text dimmed around it. */
function QuoteInContext({ finding }: { finding: Finding }) {
  const quote = isKnown(finding.quote_in_source)
    ? finding.quote_in_source.value
    : isKnown(finding.quote_as_recorded)
      ? finding.quote_as_recorded.value
      : null;

  if (!quote) return <Empty>no quote was recorded for this finding</Empty>;

  if (!finding.resolves) {
    return (
      <div className="space-y-2">
        <p className="rounded border border-amber-600/40 bg-amber-950/20 px-3 py-2 font-serif text-sm leading-relaxed text-amber-100/90">
          “{quote}”
        </p>
        <p className="text-[11px] text-amber-400/80">
          This quote no longer resolves against the stored full text. The finding is shown as
          recorded, but it cannot currently be traced to a span in the document.
        </p>
      </div>
    );
  }

  return (
    <p className="rounded border border-zinc-800 bg-zinc-950/60 px-3 py-2.5 font-serif text-sm leading-relaxed text-zinc-500">
      {finding.before && <span>…{finding.before}</span>}
      <mark className="rounded bg-sky-500/20 px-0.5 font-medium text-sky-100">{quote}</mark>
      {finding.after && <span>{finding.after}…</span>}
    </p>
  );
}

export function PublicationPage({ id }: { id: string }) {
  const publication = useQuery({
    queryKey: ["publication", id],
    queryFn: () => api.publication(id) as unknown as Promise<PublicationDetail>,
  });

  if (publication.isLoading) return <Loading what="the paper" />;
  if (publication.error) return <ErrorBox error={publication.error} />;
  const data = publication.data as unknown as PublicationDetail;

  const doi = isKnown(data.doi) ? data.doi.value : null;
  const byKind = new Map<string, Finding[]>();
  for (const finding of data.findings ?? []) {
    const kind = isKnown(finding.record_kind) ? finding.record_kind.value : "other";
    byKind.set(kind, [...(byKind.get(kind) ?? []), finding]);
  }
  const unresolved = (data.findings ?? []).filter((f) => !f.resolves).length;

  return (
    <div className="space-y-6">
      <Link to={{ name: "literature" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Literature
      </Link>

      <header>
        <h1 className="max-w-4xl text-xl font-semibold leading-snug tracking-tight text-zinc-50">
          {isKnown(data.title) ? data.title.value : data.id}
        </h1>
        <p className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-400">
          <ValueView v={data.journal} showZone={false} />
          <span className="text-zinc-700">·</span>
          <ValueView v={data.year} showZone={false} />
          {doi && (
            <>
              <span className="text-zinc-700">·</span>
              <a
                href={`https://doi.org/${doi}`}
                target="_blank"
                rel="noreferrer"
                className="font-mono text-xs text-sky-400 hover:underline"
              >
                {doi}
              </a>
            </>
          )}
        </p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Full text" className="lg:col-span-1">
          <dl>
            <Field label="State">
              <span
                className={`text-sm ${data.fulltext.is_readable ? "text-emerald-300" : "text-amber-300"}`}
              >
                {data.fulltext.display}
              </span>
            </Field>
            <Field label="Open access">
              <ValueView v={data.fulltext.oa_status} />
            </Field>
            <Field label="Licence">
              <ValueView v={data.fulltext.license} />
            </Field>
            <Field label="Media type">
              <ValueView v={data.fulltext.media_type} mono />
            </Field>
            <Field label="Characters">
              <ValueView v={data.fulltext.characters} mono />
            </Field>
            <Field label="PMID">
              <ValueView v={data.pmid} mono />
            </Field>
          </dl>
        </Panel>

        <Panel title="Screening" subtitle="one verdict per family" className="lg:col-span-2">
          {(data.screening ?? []).length === 0 ? (
            <Empty>this paper has not been screened in any family</Empty>
          ) : (
            <ul className="space-y-2">
              {data.screening.map((s) => (
                <li
                  key={s.family}
                  className="flex flex-wrap items-center justify-between gap-2 rounded border border-zinc-800 px-3 py-2"
                >
                  <div className="min-w-0">
                    <div className="truncate font-mono text-xs text-zinc-300">{s.family}</div>
                    <div className="mt-0.5 text-[11px] text-zinc-500">
                      tier {s.product_tier}
                      {isKnown(s.admitted_criterion) && ` · criterion ${s.admitted_criterion.value}`}
                    </div>
                  </div>
                  <span
                    className={`shrink-0 rounded px-2 py-0.5 text-[11px] ${
                      s.triage_state === "included"
                        ? "bg-emerald-500/10 text-emerald-300"
                        : "bg-amber-500/10 text-amber-300"
                    }`}
                  >
                    {s.triage_state}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>
      </div>

      <Panel
        title="Extracted findings"
        subtitle={
          (data.findings ?? []).length === 0
            ? "nothing has been extracted from this paper"
            : `${data.findings.length} finding(s), each shown in the sentence it came from`
        }
      >
        {(data.findings ?? []).length === 0 ? (
          <Empty>
            No findings extracted. That is not the same as “this paper contains nothing” — it
            means extraction has not run over it, or ran and proposed nothing.
          </Empty>
        ) : (
          <div className="space-y-6">
            {unresolved > 0 && (
              <Caveat>
                {unresolved} of {data.findings.length} findings no longer resolve to a span in the
                stored text. They are shown, marked, rather than dropped — a silently removed
                finding is indistinguishable from one that was never extracted.
              </Caveat>
            )}
            {[...byKind.entries()].map(([kind, findings]) => (
              <div key={kind}>
                <h3 className="mb-2 font-mono text-xs uppercase tracking-wider text-zinc-500">
                  {kind} <span className="text-zinc-700">({findings.length})</span>
                </h3>
                <ul className="space-y-3">
                  {findings.map((finding, index) => (
                    <li key={`${kind}-${index}`} className="space-y-1.5">
                      <div className="flex flex-wrap items-center gap-2 text-[11px]">
                        <span className="font-mono text-zinc-500">
                          {isKnown(finding.record_path) ? finding.record_path.value : "?"}
                        </span>
                        {isKnown(finding.section) && (
                          <span className="rounded bg-zinc-800 px-1.5 py-0.5 text-zinc-400">
                            {finding.section.value}
                          </span>
                        )}
                        {isKnown(finding.task_status) && (
                          <span
                            className={`rounded px-1.5 py-0.5 ${
                              finding.task_status.value === "accepted"
                                ? "bg-emerald-500/10 text-emerald-300"
                                : "bg-zinc-800 text-zinc-400"
                            }`}
                          >
                            {finding.task_status.value}
                          </span>
                        )}
                        {finding.char_start !== undefined && (
                          <span className="font-mono text-zinc-600">@{finding.char_start}</span>
                        )}
                      </div>
                      <QuoteInContext finding={finding} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {data.findings_truncated && (
              <p className="text-[11px] text-zinc-500">
                More findings exist than were fetched; this is a page, not a total.
              </p>
            )}
          </div>
        )}
      </Panel>
    </div>
  );
}
