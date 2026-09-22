/**
 * Annotations: the gene list, and one gene in full.
 *
 * The gene payload carries `absent_sections` — a map of the P.2 sections this page cannot fill
 * and the reason for each. That field is rendered as prominently as the content, because
 * PLAN.md O.2 point 4 says absence is reported as absence: "No studies in the atlas report X" is
 * a valid and valuable answer, and it is distinguished from "X is not the case".
 *
 * A gene page that quietly omitted its empty sections would look complete. This one looks
 * honestly partial, which is the more useful lie-free state.
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { Caveat, Field, ValueView } from "@/components/Value";
import {
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
import { api, isKnown, type Value } from "@/lib/api";

interface Annotation {
  source: string;
  term_id: string;
  term_label: Value<string>;
  namespace: Value<string>;
  evidence_code: Value<string>;
}

interface ReactionRole {
  reaction_id: string;
  reaction_name: Value<string>;
  pathway_id: Value<string>;
  compartment_id?: Value<string>;
  [key: string]: unknown;
}

interface GeneDetail {
  id: string;
  systematic_name: Value<string>;
  standard_name: Value<string>;
  organism_id: Value<string>;
  assembly_accession: Value<string>;
  gene_group_id: Value<string>;
  gene_group_anchor: Value<string>;
  annotations: Annotation[];
  reactions: ReactionRole[];
  modifications: unknown[];
  absent_sections: Record<string, string>;
  counts: Record<string, number>;
}

export function AnnotationsPage() {
  const [filter, setFilter] = useState("");
  const genes = useQuery({ queryKey: ["genes"], queryFn: () => api.genes(500) });

  if (genes.isLoading) return <Loading what="the gene list" />;
  if (genes.error) return <ErrorBox error={genes.error} />;

  const rows = genes.data!.filter(
    (gene) =>
      !filter ||
      gene.name.toLowerCase().includes(filter.toLowerCase()) ||
      gene.id.toLowerCase().includes(filter.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Annotations"
        lede="Genes anchored on their SGD systematic name, with the functional annotation attached to
              each. The anchor matters more than it looks: a paper says ADH2, the atlas keys on
              YMR303C, and the gene group is what makes those the same thing."
      />

      <StatGrid>
        <Stat label="Genes" value={genes.data!.length} hint="anchored on a gene group" />
        <Stat label="Showing" value={rows.length} hint={filter ? `matching “${filter}”` : "all"} />
      </StatGrid>

      <Panel
        title="Genes"
        subtitle="click through for annotation, reactions and what the atlas cannot fill"
        right={
          <input
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            placeholder="ADH, YMR303C…"
            className="w-48 rounded border border-zinc-700 bg-zinc-950 px-2.5 py-1 text-xs text-zinc-200 placeholder:text-zinc-600 focus:border-sky-600 focus:outline-none"
          />
        }
      >
        {rows.length === 0 ? (
          <Empty>no gene matches “{filter}”</Empty>
        ) : (
          <div className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
            {rows.map((gene) => (
              <Link
                key={gene.id}
                to={{ name: "gene", id: gene.id }}
                className="rounded border border-zinc-800 px-3 py-2 text-sm !text-zinc-200 hover:border-zinc-700 hover:bg-zinc-900 hover:!no-underline"
              >
                <div className="font-medium">{gene.name}</div>
                <div className="truncate font-mono text-[10px] text-zinc-600">{gene.id}</div>
              </Link>
            ))}
          </div>
        )}
      </Panel>
    </div>
  );
}

export function GenePage({ id }: { id: string }) {
  const gene = useQuery({
    queryKey: ["gene", id],
    queryFn: () => api.gene(id) as unknown as Promise<GeneDetail>,
  });

  if (gene.isLoading) return <Loading what="the gene" />;
  if (gene.error) return <ErrorBox error={gene.error} />;
  const data = gene.data as unknown as GeneDetail;

  const name = isKnown(data.standard_name)
    ? data.standard_name.value
    : isKnown(data.systematic_name)
      ? data.systematic_name.value
      : data.id;

  const byNamespace = new Map<string, Annotation[]>();
  for (const annotation of data.annotations ?? []) {
    const key = isKnown(annotation.namespace) ? annotation.namespace.value : "other";
    byNamespace.set(key, [...(byNamespace.get(key) ?? []), annotation]);
  }

  return (
    <div className="space-y-6">
      <Link to={{ name: "annotations" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Annotations
      </Link>

      <header>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-50">{name}</h1>
        <p className="mt-1 font-mono text-xs text-zinc-500">{data.id}</p>
      </header>

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Identity" className="lg:col-span-1">
          <dl>
            <Field label="Standard name">
              <ValueView v={data.standard_name} />
            </Field>
            <Field label="Systematic name">
              <ValueView v={data.systematic_name} mono />
            </Field>
            <Field label="Gene group">
              <ValueView v={data.gene_group_id} mono />
            </Field>
            <Field label="Anchor">
              <ValueView v={data.gene_group_anchor} mono />
            </Field>
            <Field label="Assembly">
              <ValueView v={data.assembly_accession} mono />
            </Field>
            <Field label="Organism">
              <ValueView v={data.organism_id} mono />
            </Field>
          </dl>
        </Panel>

        <Panel
          title="Reactions"
          subtitle="where this gene acts, and in which compartment"
          className="lg:col-span-2"
        >
          {(data.reactions ?? []).length === 0 ? (
            <Empty>this gene is not attached to any curated reaction</Empty>
          ) : (
            <Table head={["Reaction", "Pathway", "Compartment"]}>
              {data.reactions.map((reaction) => (
                <Row key={reaction.reaction_id}>
                  <Cell className="text-xs">
                    <ValueView v={reaction.reaction_name} showZone={false} />
                  </Cell>
                  <Cell className="font-mono text-[11px]">
                    {isKnown(reaction.pathway_id) ? (
                      <Link to={{ name: "pathway", id: reaction.pathway_id.value }}>
                        {reaction.pathway_id.value.replace("YAA:PWY:", "")}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </Cell>
                  <Cell className="font-mono text-[11px] text-zinc-400">
                    {reaction.compartment_id ? (
                      <ValueView v={reaction.compartment_id} mono showZone={false} />
                    ) : (
                      "—"
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel
        title="Functional annotation"
        subtitle={`${(data.annotations ?? []).length} term(s)`}
      >
        {(data.annotations ?? []).length === 0 ? (
          <Empty>no functional annotation is held for this gene</Empty>
        ) : (
          <div className="space-y-4">
            {[...byNamespace.entries()].map(([namespace, annotations]) => (
              <div key={namespace}>
                <h3 className="mb-1.5 font-mono text-xs uppercase tracking-wider text-zinc-500">
                  {namespace} <span className="text-zinc-700">({annotations.length})</span>
                </h3>
                <div className="flex flex-wrap gap-1.5">
                  {annotations.map((annotation) => (
                    <span
                      key={`${annotation.source}-${annotation.term_id}`}
                      title={`${annotation.source} · ${annotation.term_id}`}
                      className="rounded border border-zinc-800 bg-zinc-900/60 px-2 py-1 text-[11px] text-zinc-300"
                    >
                      {isKnown(annotation.term_label) ? annotation.term_label.value : annotation.term_id}
                      <span className="ml-1.5 font-mono text-[10px] text-zinc-600">
                        {annotation.term_id}
                      </span>
                    </span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      {Object.keys(data.absent_sections ?? {}).length > 0 && (
        <Panel
          title="What this page cannot show"
          subtitle="sections PLAN.md P.2 designs for this page, and why each is empty"
        >
          <dl className="space-y-2">
            {Object.entries(data.absent_sections).map(([section, reason]) => (
              <div key={section} className="rounded border border-dashed border-zinc-800 px-3 py-2">
                <dt className="text-xs font-medium capitalize text-zinc-400">
                  {section.replace(/_/g, " ")}
                </dt>
                <dd className="mt-0.5 text-[11px] leading-relaxed text-zinc-500">{reason}</dd>
              </div>
            ))}
          </dl>
          <Caveat tone="info">
            These sections are listed rather than omitted. An omitted section and an empty one
            look identical on a page, and only one of them is a statement about the atlas.
          </Caveat>
        </Panel>
      )}
    </div>
  );
}
