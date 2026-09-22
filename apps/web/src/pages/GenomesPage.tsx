/**
 * Genomes: the references on disk, and the genetic code each compartment reads.
 *
 * This is not a genome browser and does not pretend to be one. What the isobutanol and
 * mitochondrial programs turn on is which code table applies where, so the code table leads.
 *
 * The dual-coded compartments get their own panel at the top, because a sequence filed against
 * the mitochondrial matrix without declaring its code table is ambiguous, and the failure mode
 * is not subtle: table 1 reads `CUN` as leucine and `UGA` as stop, table 3 reads them as
 * threonine and tryptophan. A gene moved between them without recoding truncates.
 */

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, CheckCircle2, CircleSlash } from "lucide-react";

import { Caveat, Field, ValueView } from "@/components/Value";
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
import { api, isKnown } from "@/lib/api";

function bytes(n: number | null): string {
  if (n === null) return "—";
  if (n > 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  if (n > 1e3) return `${(n / 1e3).toFixed(0)} kB`;
  return `${n} B`;
}

export function GenomesPage() {
  const genomes = useQuery({ queryKey: ["genomes"], queryFn: api.genomes });

  if (genomes.isLoading) return <Loading what="the reference layer" />;
  if (genomes.error) return <ErrorBox error={genomes.error} />;
  const data = genomes.data!;

  const dual = data.compartments.filter((c) => c.is_dual_coded);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Genomes"
        lede="Which references are on disk, and which genetic code applies inside each compartment.
              The second question is the one that bites: two compartments here are read by two
              different code tables, and a sequence filed against them is ambiguous until it says
              which one it was written for."
      />

      <StatGrid>
        <Stat label="Reference sequences" value={data.references.length} hint="on disk, with checksums" />
        <Stat label="Assembly assets" value={data.assets.length} hint="genomes held for comparison" />
        <Stat
          label="Dual-coded compartments"
          value={dual.length}
          tone={dual.length > 0 ? "warn" : "default"}
          hint="read by more than one genetic code"
        />
        <Stat label="mtDNA loci" value={data.mtdna_loci.length} hint="candidate insertion sites" />
      </StatGrid>

      {dual.length > 0 && (
        <Panel
          title="Dual-coded compartments"
          subtitle="a sequence filed here must declare the code table it was written for"
        >
          <div className="grid gap-3 sm:grid-cols-2">
            {dual.map((compartment) => (
              <div
                key={compartment.id}
                className="rounded border border-amber-600/40 bg-amber-950/10 p-3"
              >
                <div className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-400" />
                  <div className="min-w-0">
                    <div className="font-mono text-sm text-amber-200">{compartment.id}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5">
                      {compartment.encoding_genomes.map((genome) => (
                        <span
                          key={genome}
                          className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[11px] text-amber-200"
                        >
                          {genome}
                        </span>
                      ))}
                    </div>
                    {compartment.warning && (
                      <p className="mt-2 text-[11px] leading-relaxed text-amber-200/70">
                        {compartment.warning}
                      </p>
                    )}
                  </div>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Genetic codes" subtitle="the table, the ribosome that reads it, and where it applies">
          <div className="space-y-3">
            {data.encoding_genomes.map((genome) => (
              <div key={genome.id} className="rounded border border-zinc-800 p-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="font-mono text-sm text-zinc-100">{genome.id}</span>
                  <span className="rounded bg-sky-500/10 px-2 py-0.5 font-mono text-xs text-sky-300">
                    table {genome.genetic_code_table}
                  </span>
                </div>
                <dl className="mt-2">
                  <Field label="Name">
                    <ValueView v={genome.table_name} />
                  </Field>
                  <Field label="Ribosome">
                    <ValueView v={genome.ribosome} />
                  </Field>
                  <Field label="Applies in">
                    <span className="text-sm text-zinc-300">
                      {genome.compartments.length} compartment
                      {genome.compartments.length === 1 ? "" : "s"}
                    </span>
                  </Field>
                </dl>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Compartments" subtitle="import machinery and the code(s) read inside">
          <Table head={["Compartment", "Import", "Codes"]}>
            {data.compartments.map((compartment) => (
              <Row key={compartment.id}>
                <Cell className="font-mono text-xs">
                  {compartment.id}
                  {compartment.is_dual_coded && (
                    <AlertTriangle className="ml-1.5 inline h-3 w-3 text-amber-400" />
                  )}
                </Cell>
                <Cell className="text-xs">
                  <ValueView v={compartment.import_machinery} showZone={false} />
                </Cell>
                <Cell className="font-mono text-[11px] text-zinc-400">
                  {compartment.encoding_genomes.join(", ") || "—"}
                </Cell>
              </Row>
            ))}
          </Table>
        </Panel>
      </div>

      <Panel title="Reference sequences" subtitle="what is actually on disk, with translation verification">
        <Table head={["Id", "Kind", "Accession", "Code", "Size", "Translation verified"]}>
          {data.references.map((reference) => (
            <Row key={reference.id}>
              <Cell className="font-mono text-[11px]">{reference.id}</Cell>
              <Cell className="text-xs text-zinc-400">{reference.kind}</Cell>
              <Cell className="font-mono text-xs">
                <ValueView v={reference.accession} mono showZone={false} />
              </Cell>
              <Cell className="font-mono text-[11px]">
                <ValueView v={reference.encoding_genome} mono showZone={false} />
              </Cell>
              <Cell className="font-mono text-xs text-zinc-500">{bytes(reference.size_bytes)}</Cell>
              <Cell>
                {reference.translation_verified === null ? (
                  <span className="text-xs italic text-zinc-600">not applicable</span>
                ) : reference.translation_verified ? (
                  <span className="inline-flex items-center gap-1 text-xs text-emerald-300">
                    <CheckCircle2 className="h-3.5 w-3.5" /> verified
                  </span>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-zinc-500">
                    <CircleSlash className="h-3.5 w-3.5" /> not run
                  </span>
                )}
              </Cell>
            </Row>
          ))}
        </Table>
      </Panel>

      <Panel
        title="mtDNA loci"
        subtitle="candidate sites, and what displacing each one costs"
      >
        {data.mtdna_loci.length === 0 ? (
          <Empty>no mitochondrial loci recorded</Empty>
        ) : (
          <Table head={["Locus", "Encodes", "Respiration retained", "Rescue available"]}>
            {data.mtdna_loci.map((locus) => (
              <Row key={locus.id}>
                <Cell className="font-mono text-xs text-zinc-200">{locus.locus}</Cell>
                <Cell className="max-w-md text-xs">
                  <ValueView v={locus.encodes} showZone={false} />
                </Cell>
                <Cell>
                  {locus.respiration_retained_if_used === null ? (
                    <span className="text-xs italic text-zinc-600">not recorded</span>
                  ) : locus.respiration_retained_if_used ? (
                    <span className="text-xs text-emerald-300">retained</span>
                  ) : (
                    <span className="text-xs text-red-300">lost</span>
                  )}
                </Cell>
                <Cell className="text-xs">
                  {isKnown(locus.rescue_available) ? (
                    <span className="text-emerald-300">{locus.rescue_available.value}</span>
                  ) : (
                    <ValueView v={locus.rescue_available} showZone={false} />
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Assembly assets" subtitle="genomes held for comparison">
          <Table head={["Organism", "Accession", "Size"]}>
            {data.assets.map((asset) => (
              <Row key={asset.id}>
                <Cell className="text-xs">
                  <ValueView v={asset.organism} showZone={false} />
                </Cell>
                <Cell className="font-mono text-[11px]">
                  <ValueView v={asset.accession} mono showZone={false} />
                </Cell>
                <Cell className="font-mono text-xs text-zinc-500">{bytes(asset.size_bytes)}</Cell>
              </Row>
            ))}
          </Table>
        </Panel>
        <Panel title="Strains by class" subtitle={`${data.organisms.length} organisms`}>
          <BarList data={Object.entries(data.strains_by_class).sort((a, b) => b[1] - a[1])} />
        </Panel>
      </div>

      <Caveat tone="info">
        Translation verification is only meaningful for the mitochondrial reference, where the
        code table is the whole risk — a nuclear sequence read under table 1 has nothing to
        verify against. “Not applicable” and “not run” therefore render differently above.
      </Caveat>
    </div>
  );
}
