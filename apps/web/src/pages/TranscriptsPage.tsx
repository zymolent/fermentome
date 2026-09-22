/**
 * Transcripts: the sequencing studies, and what each one can actually support.
 *
 * "172 runs across 15 studies" reads like a transcriptome atlas. It is not one, and the columns
 * that say so lead the page: how many runs are RNA-Seq rather than amplicon or Tn-Seq, how many
 * are downloaded rather than merely discovered, and how many were quantified against the right
 * strain's assembly.
 *
 * Each study carries a `usable_note` computed in the query layer rather than assembled here, so
 * the judgement travels with the data to every consumer — the API, an export, a notebook — and
 * not just to this page.
 */

import { useQuery } from "@tanstack/react-query";

import { Caveat, ValueView } from "@/components/Value";
import {
  BarList,
  Cell,
  Empty,
  ErrorBox,
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

export function TranscriptsPage({ route }: { route: Extract<Route, { name: "transcripts" }> }) {
  const overview = useQuery({ queryKey: ["transcripts"], queryFn: api.transcripts });
  const runs = useQuery({
    queryKey: ["runs", route.study],
    queryFn: () => api.runs({ study: route.study, limit: 200 }),
    enabled: !!route.study,
  });

  if (overview.isLoading) return <Loading what="the omics inventory" />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const data = overview.data!;

  const downloaded = data.by_acquisition_status.downloaded ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transcripts"
        lede="Sequencing studies and their runs. A run that is discovered is not a run that is
              downloaded, and a run quantified against another strain's assembly cannot see a
              heterologous cassette at all — so the counts are split by what each run can support
              rather than totalled."
      />

      <StatGrid>
        <Stat label="Studies" value={data.studies.length} hint={`${data.datasets} dataset records`} />
        <Stat
          label="RNA-Seq runs"
          value={data.expression_runs}
          hint={`of ${data.runs} total runs — the rest are amplicon, Tn-Seq or WGS`}
        />
        <Stat
          label="Downloaded"
          value={downloaded}
          tone={downloaded === 0 ? "warn" : "good"}
          hint={downloaded === 0 ? "accessions only — no reads are on disk" : "reads on disk"}
        />
        <Stat
          label="Samples with context"
          value={`${data.samples_with_context} / ${data.samples}`}
          tone={data.samples_without_context > 0 ? "warn" : "good"}
          hint="a sample with no condition context cannot enter a contrast"
        />
      </StatGrid>

      {downloaded === 0 && (
        <Caveat>
          No run has been downloaded. Every study below is an accession list: the atlas knows
          these experiments exist and has not yet quantified any of them, so nothing here can
          currently support an expression statement.
        </Caveat>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Library strategy" subtitle="only RNA-Seq measures expression">
          <BarList data={Object.entries(data.by_strategy).sort((a, b) => b[1] - a[1])} />
        </Panel>
        <Panel title="Acquisition" subtitle="discovered is not downloaded">
          <BarList data={Object.entries(data.by_acquisition_status).sort((a, b) => b[1] - a[1])} />
        </Panel>
        <Panel
          title="Reference match"
          subtitle="species_exact means another strain's assembly was used"
        >
          <BarList data={Object.entries(data.by_reference_match).sort((a, b) => b[1] - a[1])} />
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
            For an engineered strain carrying a heterologous cassette, quantifying against the
            species reference reads the transgene as absent rather than as zero.
          </p>
        </Panel>
      </div>

      <Panel
        title="Studies"
        subtitle="each with what its runs can and cannot support"
        right={
          route.study && (
            <button
              onClick={() => navigate({ name: "transcripts" })}
              className="text-[11px] text-zinc-500 hover:text-zinc-300"
            >
              clear filter
            </button>
          )
        }
      >
        <Table head={["Study", "Organism", "Runs", "RNA-Seq", "Strain-matched", "Assessment"]}>
          {data.studies.map((study) => (
            <Row key={study.study_accession}>
              <Cell>
                <button
                  onClick={() => navigate({ name: "transcripts", study: study.study_accession })}
                  className={`font-mono text-xs ${
                    route.study === study.study_accession ? "text-sky-300" : "text-sky-400 hover:underline"
                  }`}
                >
                  {study.study_accession}
                </button>
              </Cell>
              <Cell className="max-w-[16rem] truncate text-xs">
                <ValueView v={study.organism} showZone={false} />
              </Cell>
              <Cell className="font-mono text-xs tabular-nums">{study.runs}</Cell>
              <Cell className="font-mono text-xs tabular-nums">
                {study.expression_runs || <span className="text-zinc-600">0</span>}
              </Cell>
              <Cell className="font-mono text-xs tabular-nums">
                {study.strain_matched || <span className="text-zinc-600">0</span>}
              </Cell>
              <Cell className="max-w-sm text-[11px] leading-snug text-zinc-500">
                {study.usable_note}
              </Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      {route.study && (
        <Panel title={`Runs in ${route.study}`} subtitle="every run, as the archive describes it">
          {runs.isLoading ? (
            <Loading what="runs" />
          ) : runs.error ? (
            <ErrorBox error={runs.error} />
          ) : runs.data!.rows.length === 0 ? (
            <Empty>no runs recorded for this study</Empty>
          ) : (
            <Table head={["Run", "Strategy", "Layout", "Platform", "Spots", "Reference", "Status"]}>
              {runs.data!.rows.map((run) => {
                const row = run as Record<string, string | number | null>;
                return (
                  <Row key={String(row.id)}>
                    <Cell className="font-mono text-xs text-zinc-200">{String(row.run_accession)}</Cell>
                    <Cell className="text-xs">{String(row.library_strategy ?? "—")}</Cell>
                    <Cell className="text-xs text-zinc-500">{String(row.library_layout ?? "—")}</Cell>
                    <Cell className="text-xs text-zinc-500">{String(row.platform ?? "—")}</Cell>
                    <Cell className="font-mono text-xs tabular-nums text-zinc-500">
                      {row.spots ? Number(row.spots).toLocaleString() : "—"}
                    </Cell>
                    <Cell className="text-[11px] text-zinc-500">
                      {String(row.reference_match_quality ?? "—")}
                    </Cell>
                    <Cell className="text-xs">
                      <span
                        className={
                          row.acquisition_status === "excluded" ? "text-zinc-600" : "text-amber-300"
                        }
                      >
                        {String(row.acquisition_status ?? "—")}
                      </span>
                    </Cell>
                  </Row>
                );
              })}
            </Table>
          )}
        </Panel>
      )}

      <Panel title="Analyses held" subtitle="results computed from these runs">
        {Object.keys(data.analyses).length === 0 ? (
          <Empty>no analysis results recorded</Empty>
        ) : (
          <BarList data={Object.entries(data.analyses).sort((a, b) => b[1] - a[1])} />
        )}
      </Panel>
    </div>
  );
}
