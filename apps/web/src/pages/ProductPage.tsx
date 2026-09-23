/**
 * Products: the tier list, and everything the atlas holds for one product.
 *
 * PLAN.md P.2: "The class-faceted comparison, never a global leaderboard." PLAN.md I.2 says why —
 * the atlas **refuses** to produce a global "best strain" ranking, because that number would be
 * read as meaningful and would not be.
 *
 * So this page has no sorted list of titers anywhere on it. Measurements arrive from the server
 * already grouped by comparability class, and each group carries `is_rankable` and, when that is
 * false, the `refusal_reason` that says which of the four conditions failed. A group that is
 * rankable shows its best per (kind, unit); a group that is not shows its rows in id order with
 * the refusal printed above them. Today every group is the single `unclassified` one, because no
 * measurement carries a `sample_id` — the refusal is not a hypothetical branch, it is the page.
 *
 * The refusal text itself comes from the server (`leaderboard_refusal`) rather than being
 * written here, so any other consumer of `/api/products/{id}` gets it too. A refusal that only
 * exists in the HTML is a refusal the next client will not make.
 */

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";

import { ClassHeader } from "@/components/Comparability";
import { Caveat, Field, QuantityView, ValueView } from "@/components/Value";
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
import { api, isKnown, type ClassFacetedMeasurements } from "@/lib/api";

const TIER_STYLE: Record<string, string> = {
  primary: "bg-sky-500/10 text-sky-300 ring-sky-500/30",
  reference: "bg-emerald-500/10 text-emerald-300 ring-emerald-500/30",
  adjacent: "bg-zinc-800 text-zinc-300 ring-zinc-700",
  reserved: "bg-zinc-900 text-zinc-500 ring-zinc-800",
};

function TierBadge({ tier }: { tier: string }) {
  return (
    <span
      className={`inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ring-1 ring-inset ${
        TIER_STYLE[tier] ?? TIER_STYLE.adjacent
      }`}
    >
      {tier}
    </span>
  );
}

export function ProductsPage() {
  const products = useQuery({ queryKey: ["products"], queryFn: api.products });

  if (products.isLoading) return <Loading what="the products" />;
  if (products.error) return <ErrorBox error={products.error} />;
  const rows = products.data!;

  const reserved = rows.filter((row) => isKnown(row.tier) && row.tier.value === "reserved");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Products"
        lede="PLAN.md B.1's four tiers. `reserved` rows exist to prove the schema is
              product-generic and are expected to stay empty — an empty reserved product is the
              design working, not a gap."
      />

      <StatGrid>
        <Stat label="Products" value={rows.length} hint="a controlled vocabulary, not a table" />
        <Stat
          label="With a measurement"
          value={rows.filter((row) => row.measurements > 0).length}
          hint="the rest carry a definition and nothing measured"
        />
        <Stat
          label="With a theoretical yield"
          value={rows.filter((row) => row.theoretical_yields > 0).length}
          hint="cited per (product, substrate) — never computed on the fly"
        />
        <Stat
          label="Reserved"
          value={reserved.length}
          tone="muted"
          hint="expected to be empty; they prove the schema is not isobutanol-shaped"
        />
      </StatGrid>

      <Panel title="All products" subtitle="ordered by tier, then name — never by any number">
        <Table head={["Product", "Tier", "Measurements", "Strains", "Configurations", "Yields"]}>
          {rows.map((row) => (
            <Row key={row.id}>
              <Cell>
                <Link to={{ name: "product", id: row.id }}>{row.name}</Link>
              </Cell>
              <Cell>{isKnown(row.tier) ? <TierBadge tier={row.tier.value} /> : <ValueView v={row.tier} />}</Cell>
              <Cell className="font-mono text-xs tabular-nums">{row.measurements || "—"}</Cell>
              <Cell className="font-mono text-xs tabular-nums">{row.strains || "—"}</Cell>
              <Cell className="font-mono text-xs tabular-nums">{row.configurations || "—"}</Cell>
              <Cell className="font-mono text-xs tabular-nums">{row.theoretical_yields || "—"}</Cell>
            </Row>
          ))}
        </Table>
      </Panel>
    </div>
  );
}

/** One class's measurements, with its best only where a best may be named. */
function ClassPanel({ group }: { group: ClassFacetedMeasurements }) {
  const best = Object.entries(group.best);
  return (
    <div className="space-y-3 rounded border border-zinc-800/70 p-3">
      <ClassHeader
        klass={group.class}
        right={
          <span className="shrink-0 text-[11px] text-zinc-500">
            {group.count} measurement{group.count === 1 ? "" : "s"} · {group.kinds.length} kind(s)
          </span>
        }
      />

      {group.is_rankable ? (
        <div className="grid gap-2 sm:grid-cols-2">
          {best.map(([key, row]) => (
            <div key={key} className="rounded border border-emerald-700/40 bg-emerald-950/20 px-3 py-2">
              <div className="text-[10px] uppercase tracking-wider text-emerald-400/70">
                best in class — {key}
              </div>
              <div className="mt-1">
                <QuantityView q={row.quantity} />
              </div>
              <div className="mt-1 text-[11px] text-zinc-500">
                {isKnown(row.strain_id) ? (
                  <Link to={{ name: "strain", id: row.strain_id.value }}>
                    {row.strain_id.value.replace("YAA:STRAIN:", "")}
                  </Link>
                ) : (
                  <ValueView v={row.strain_id} showZone={false} />
                )}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="rounded border border-zinc-800 bg-zinc-950/50 px-3 py-2 text-[11px] leading-relaxed text-zinc-400">
          <span className="font-medium text-zinc-300">No best is named here.</span>{" "}
          {group.refusal_reason}
        </p>
      )}

      <Table head={["Value", "Kind", "Strain", "Basis", "Source"]}>
        {group.measurements.map((row) => (
          <Row key={row.id}>
            <Cell>
              <QuantityView q={row.quantity} />
            </Cell>
            <Cell className="text-xs">
              <span className={row.is_controlled_kind ? "text-zinc-300" : "text-amber-300/80"}>
                {row.quantity_kind.length > 36
                  ? `${row.quantity_kind.slice(0, 36)}…`
                  : row.quantity_kind}
              </span>
            </Cell>
            <Cell className="text-[11px]">
              {isKnown(row.strain_id) ? (
                <Link to={{ name: "strain", id: row.strain_id.value }}>
                  {row.strain_id.value.replace("YAA:STRAIN:", "")}
                </Link>
              ) : (
                <ValueView v={row.strain_id} showZone={false} />
              )}
            </Cell>
            <Cell className="text-[11px]">
              <ValueView v={row.basis} showZone={false} />
            </Cell>
            <Cell className="text-[11px]">
              {isKnown(row.publication_id) ? (
                <Link to={{ name: "publication", id: row.publication_id.value }}>paper</Link>
              ) : (
                <ValueView v={row.publication_id} showZone={false} />
              )}
            </Cell>
          </Row>
        ))}
      </Table>
    </div>
  );
}

export function ProductPage({ id }: { id: string }) {
  const product = useQuery({ queryKey: ["product", id], queryFn: () => api.product(id) });

  if (product.isLoading) return <Loading what="the product" />;
  if (product.error) return <ErrorBox error={product.error} />;
  const data = product.data!;

  const measurements = data.classes.reduce((total, group) => total + group.count, 0);
  const classified = data.classes.filter((group) => group.class.is_classified).length;

  return (
    <div className="space-y-6">
      <Link to={{ name: "products" }} className="inline-flex items-center gap-1.5 text-xs">
        <ArrowLeft className="h-3 w-3" /> Products
      </Link>

      <header>
        <h1 className="flex flex-wrap items-center gap-3 text-xl font-semibold tracking-tight text-zinc-50">
          {data.name}
          {isKnown(data.tier) && <TierBadge tier={data.tier.value} />}
        </h1>
        <p className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-zinc-400">
          <ValueView v={data.formula} mono showZone={false} />
          <span className="text-zinc-700">·</span>
          <ValueView v={data.mw_g_mol} mono showZone={false} />
          <span className="text-zinc-700">·</span>
          <span className="font-mono text-xs text-zinc-600">{data.id}</span>
        </p>
      </header>

      <StatGrid>
        <Stat label="Measurements" value={measurements} hint={`across ${data.strains.length} strain(s)`} />
        <Stat
          label="Comparability classes"
          value={data.classes.length}
          tone={classified === 0 ? "warn" : "good"}
          hint={`${classified} of them classified — the rest support no comparison`}
        />
        <Stat label="Pathways" value={data.pathways.length} hint={`${data.configurations.length} configuration(s)`} />
        <Stat
          label="Theoretical yields"
          value={data.theoretical_yields.length}
          hint="cited per substrate, never computed on the fly"
        />
      </StatGrid>

      <Caveat>{data.leaderboard_refusal}</Caveat>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Identity" subtitle="what this product is, as the atlas records it">
          <dl>
            <Field label="InChIKey">
              <ValueView v={data.inchikey} mono />
            </Field>
            <Field label="ChEBI">
              <ValueView v={data.chebi_id} mono />
            </Field>
            <Field label="Carbon number">
              <ValueView v={data.carbon_number} mono />
            </Field>
            <Field label="Canonical unit">
              <ValueView v={data.canonical_unit} mono />
            </Field>
            <Field label="Zone">
              <ValueView v={data.zone} />
            </Field>
          </dl>
        </Panel>

        <Panel
          title="Theoretical yield"
          subtitle="per substrate — 0.411 g/g is a statement about glucose, not about the product"
        >
          {data.theoretical_yields.length === 0 ? (
            <Empty>no theoretical yield is recorded for this product</Empty>
          ) : (
            <Table head={["Substrate", "g/g", "mol/mol", "Stoichiometry"]}>
              {data.theoretical_yields.map((row) => (
                <Row key={row.substrate}>
                  <Cell className="text-xs text-zinc-200">{row.substrate}</Cell>
                  <Cell>
                    <ValueView v={row.g_per_g} mono />
                  </Cell>
                  <Cell>
                    <ValueView v={row.mol_per_mol} mono />
                  </Cell>
                  <Cell className="font-mono text-[10px] text-zinc-400">
                    <ValueView v={row.stoichiometry} showZone={false} />
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel
        title="Measurements by comparability class"
        subtitle="the class-faceted comparison — never a ranking across classes"
      >
        {data.classes.length === 0 ? (
          <Empty>no measurement in the atlas names this product</Empty>
        ) : (
          <div className="space-y-4">
            {data.classes.map((group) => (
              <ClassPanel key={group.class.key} group={group} />
            ))}
            {data.measurements_truncated && (
              <p className="text-[11px] text-zinc-500">This is a page, not a total.</p>
            )}
          </div>
        )}
      </Panel>

      <div className="grid gap-6 lg:grid-cols-2">
        <Panel title="Pathways" subtitle={data.pathway_note}>
          {data.pathways.length === 0 ? (
            <Empty>{data.pathway_note}</Empty>
          ) : (
            <ul className="space-y-2">
              {data.pathways.map((pathway) => (
                <li key={pathway.id} className="flex items-baseline justify-between gap-3">
                  <Link to={{ name: "pathway", id: pathway.id }} className="text-sm">
                    {pathway.name}
                  </Link>
                  <span className="shrink-0 text-[11px] text-zinc-500">
                    {pathway.reactions} reaction(s)
                    {!pathway.linked_directly && (
                      <span className="ml-2 text-amber-400/70" title={data.pathway_note}>
                        indirect
                      </span>
                    )}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel title="Strategies" subtitle="pathway configurations proposed for this product">
          {data.configurations.length === 0 ? (
            <Empty>no pathway configuration names this product</Empty>
          ) : (
            <Table head={["Strategy", "Host strain", "Pathway"]}>
              {data.configurations.map((config) => (
                <Row key={config.id}>
                  <Cell className="font-mono text-[11px] text-zinc-200">
                    {config.compartment_strategy_id ?? "—"}
                  </Cell>
                  <Cell className="text-[11px]">
                    {config.host_strain_id ? (
                      <Link to={{ name: "strain", id: config.host_strain_id }}>
                        {config.host_strain_name ?? config.host_strain_id}
                      </Link>
                    ) : (
                      <span className="italic text-zinc-500 underline decoration-dashed decoration-zinc-600 underline-offset-2">
                        not recorded
                      </span>
                    )}
                  </Cell>
                  <Cell className="text-[11px]">
                    {config.pathway_id ? (
                      <Link to={{ name: "pathway", id: config.pathway_id }}>
                        {config.pathway_id.replace("YAA:PWY:", "")}
                      </Link>
                    ) : (
                      <span className="text-zinc-600">—</span>
                    )}
                  </Cell>
                </Row>
              ))}
            </Table>
          )}
        </Panel>
      </div>

      <Panel title="Tolerance" subtitle="what the atlas can record about tolerance to this product">
        {data.tolerance.length === 0 ? (
          <div className="space-y-3">
            <Empty>no tolerance figure is recorded</Empty>
            <Caveat>{data.tolerance_note}</Caveat>
          </div>
        ) : (
          <div className="space-y-3">
            <Table head={["Chassis", "Tolerance", "Endpoint", "Selected"]}>
              {data.tolerance.map((profile) => (
                <Row key={profile.id}>
                  <Cell className="text-xs text-zinc-200">{profile.name_as_reported}</Cell>
                  <Cell>
                    <ValueView v={profile.tolerance} mono />
                  </Cell>
                  <Cell>
                    <ValueView v={profile.tolerance_endpoint} showZone={false} />
                  </Cell>
                  <Cell className="text-[11px] text-zinc-500">
                    {profile.is_selected ? "selected" : "—"}
                  </Cell>
                </Row>
              ))}
            </Table>
            <Caveat tone="info">{data.tolerance_note}</Caveat>
          </div>
        )}
      </Panel>
    </div>
  );
}
