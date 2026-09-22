/**
 * Data: the measurements, and why most of them cannot yet be compared to each other.
 *
 * PLAN.md P.2 for the Product page: "The class-faceted comparison, never a global leaderboard."
 * The atlas cannot currently produce either, and the honest reason is worth stating plainly on
 * the page: no measurement is attached to a sample, so no measurement can reach a condition
 * context, so no comparability class can be computed for any of them.
 *
 * That makes a "best titer" table actively misleading — 32 rows in g/L and 32 in mg/L, measured
 * under conditions the atlas cannot compare. So the table shows the reported value with its unit
 * as reported and carries every row's warnings inline, rather than sorting by a normalized
 * number that would imply a comparison the data does not support.
 */

import { useQuery } from "@tanstack/react-query";

import { Caveat, QuantityView, ValueView } from "@/components/Value";
import {
  BarList,
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
import { api, isKnown } from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

export function DataPage({ route }: { route: Extract<Route, { name: "data" }> }) {
  const overview = useQuery({ queryKey: ["data-overview"], queryFn: api.dataOverview });
  const measurements = useQuery({
    queryKey: ["measurements", route.kind],
    queryFn: () => api.measurements({ quantity_kind: route.kind, limit: 100 }),
  });

  if (overview.isLoading) return <Loading what="the measurements" />;
  if (overview.error) return <ErrorBox error={overview.error} />;
  const data = overview.data!;

  const quarantined = data.quality_severity.quarantine ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data"
        lede="Titers, yields and tolerances as the papers reported them. The page leads with what
              blocks comparison rather than with a leaderboard, because the join that comparability
              is built on — measurement to sample to condition context — is not yet populated for a
              single row."
      />

      <StatGrid>
        <Stat label="Measurements" value={data.measurements} hint={`across ${data.experiments} experiments`} />
        <Stat
          label="Reaching a condition context"
          value={data.measurements_with_sample}
          tone={data.measurements_with_sample === 0 ? "warn" : "good"}
          hint="via a sample — required for a comparability class"
        />
        <Stat label="Strains" value={data.strains} hint={`${data.products} products`} />
        <Stat
          label="Quarantined"
          value={quarantined}
          tone={quarantined > 0 ? "warn" : "default"}
          hint={`${data.quality_severity.warn ?? 0} further rows flagged as warnings`}
        />
      </StatGrid>

      {data.measurements_with_sample === 0 && (
        <Caveat>{data.join_note}</Caveat>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Panel title="Quantity kinds" subtitle="only the recurring ones are charted">
          <BarList
            data={Object.entries(data.by_quantity_kind).sort((a, b) => b[1] - a[1])}
            onSelect={(kind) => navigate({ name: "data", kind: kind === route.kind ? undefined : kind })}
          />
          <p className="mt-3 text-[11px] leading-relaxed text-zinc-500">
            {data.quantity_kind_note}
          </p>
        </Panel>
        <Panel title="Units as reported" subtitle={data.unit_note}>
          <BarList data={Object.entries(data.by_unit).sort((a, b) => b[1] - a[1])} />
        </Panel>
        <Panel title="Quality flags" subtitle="what the detectors raised">
          <BarList data={Object.entries(data.quality_flags).sort((a, b) => b[1] - a[1])} />
          <div className="mt-4">
            <div className="mb-1.5 text-[10px] uppercase tracking-wider text-zinc-600">By product</div>
            <BarList
              data={Object.entries(data.by_product)
                .sort((a, b) => b[1] - a[1])
                .map(([key, n]) => [key.replace("YAA:PRODUCT:", ""), n] as [string, number])}
            />
          </div>
        </Panel>
      </div>

      <Panel
        title="Measurements"
        subtitle={
          route.kind
            ? `quantity_kind = ${route.kind}`
            : "as reported, with each row's comparability caveats"
        }
        right={
          route.kind && (
            <button
              onClick={() => navigate({ name: "data" })}
              className="text-[11px] text-zinc-500 hover:text-zinc-300"
            >
              clear filter
            </button>
          )
        }
      >
        {measurements.isLoading ? (
          <Loading what="measurements" />
        ) : measurements.error ? (
          <ErrorBox error={measurements.error} />
        ) : measurements.data!.rows.length === 0 ? (
          <Empty>no measurement matches this filter</Empty>
        ) : (
          <Table head={["Value", "Kind", "Strain", "Product", "Source", "Caveats"]}>
            {measurements.data!.rows.map((row) => (
              <Row key={row.id}>
                <Cell>
                  <QuantityView q={row.quantity} />
                </Cell>
                <Cell className="text-xs">
                  <span className={row.is_controlled_kind ? "text-zinc-300" : "text-amber-300/80"}>
                    {row.quantity_kind.length > 34
                      ? `${row.quantity_kind.slice(0, 34)}…`
                      : row.quantity_kind}
                  </span>
                </Cell>
                <Cell className="font-mono text-[11px]">
                  <ValueView v={row.strain_id} mono showZone={false} />
                </Cell>
                <Cell className="font-mono text-[11px] text-zinc-400">
                  {isKnown(row.product_id) ? row.product_id.value.replace("YAA:PRODUCT:", "") : "—"}
                </Cell>
                <Cell className="text-[11px]">
                  {isKnown(row.publication_id) ? (
                    <Link to={{ name: "publication", id: row.publication_id.value }}>paper</Link>
                  ) : (
                    <ValueView v={row.publication_id} showZone={false} />
                  )}
                </Cell>
                <Cell>
                  {row.comparability_warnings.length === 0 ? (
                    <span className="text-[11px] text-zinc-600">—</span>
                  ) : (
                    <details className="text-[11px]">
                      <summary
                        className={`cursor-pointer ${
                          row.flags.some((f) => f.severity === "quarantine")
                            ? "text-red-400"
                            : "text-amber-400/80"
                        }`}
                      >
                        {row.comparability_warnings.length} caveat
                        {row.comparability_warnings.length === 1 ? "" : "s"}
                      </summary>
                      <ul className="mt-1.5 space-y-1 text-zinc-500">
                        {row.comparability_warnings.map((warning, index) => (
                          <li key={index} className="leading-snug">
                            · {warning}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </Cell>
              </Row>
            ))}
          </Table>
        )}
        {measurements.data?.truncated && (
          <p className="mt-3 text-[11px] text-zinc-500">This is a page, not a total.</p>
        )}
      </Panel>

      <Caveat tone="info">
        Values are shown as reported, in the unit the paper used. Sorting them into a single
        ranking would require a comparability class, which requires a condition context, which
        requires the measurement-to-sample join — so the leaderboard PLAN.md P.2 describes is a
        page this atlas cannot yet honestly draw.
      </Caveat>
    </div>
  );
}
