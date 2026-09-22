/**
 * Search: results grouped by kind, never merged into one ranked list.
 *
 * Merging would imply a scoring function that compares "a paper whose title contains the word"
 * with "a strain whose name is exactly the word". No such function exists here, so the groups
 * stay separate and the page says what the matching technique actually is — substring, not
 * semantic — so a reader knows a miss may be a synonym rather than an absence.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search as SearchIcon } from "lucide-react";

import { Caveat } from "@/components/Value";
import { Empty, ErrorBox, Link, Loading, PageHeader, Panel } from "@/components/ui";
import { api } from "@/lib/api";
import { navigate, type Route } from "@/lib/router";

/** Where a hit of each kind leads. A kind with no detail page stays plain text. */
function hitRoute(kind: string, row: Record<string, unknown>): Route | null {
  const id = String(row.id ?? "");
  switch (kind) {
    case "publication":
      return { name: "publication", id };
    case "gene":
      return { name: "gene", id };
    case "pathway":
      return { name: "pathway", id };
    default:
      return null;
  }
}

/** The most human-readable column each kind has, falling back to the id. */
function hitLabel(row: Record<string, unknown>): string {
  for (const key of ["title", "standard_name", "canonical_name", "name", "id"]) {
    const value = row[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return String(row.id ?? "?");
}

function hitDetail(kind: string, row: Record<string, unknown>): string {
  switch (kind) {
    case "publication":
      return [row.year, row.journal].filter(Boolean).join(" · ");
    case "gene":
      return String(row.systematic_name ?? "");
    case "strain":
      return String(row.class ?? "");
    case "reaction":
      return [row.ec_number, row.compartment_id].filter(Boolean).join(" · ");
    case "product":
      return String(row.tier ?? "");
    default:
      return String(row.id ?? "");
  }
}

export function SearchPage({ route }: { route: Extract<Route, { name: "search" }> }) {
  const [term, setTerm] = useState(route.q);

  useEffect(() => setTerm(route.q), [route.q]);

  const hits = useQuery({
    queryKey: ["search", route.q],
    queryFn: () => api.search(route.q, 15),
    enabled: route.q.trim().length > 0,
  });

  return (
    <div className="space-y-6">
      <PageHeader
        title="Search"
        lede="One box over publications, genes, gene groups, strains, products, metabolites,
              reactions and pathways. Results stay grouped by kind because nothing here can rank a
              paper against a strain."
      />

      <form
        onSubmit={(event) => {
          event.preventDefault();
          navigate({ name: "search", q: term });
        }}
        className="flex items-center gap-2"
      >
        <div className="relative flex-1">
          <SearchIcon className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-600" />
          <input
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            autoFocus
            placeholder="isobutanol, ADH2, CEN.PK, YMR303C…"
            className="w-full rounded border border-zinc-700 bg-zinc-950 py-2 pl-9 pr-3 text-sm text-zinc-200 placeholder:text-zinc-600 focus:border-sky-600 focus:outline-none"
          />
        </div>
        <button
          type="submit"
          className="rounded border border-sky-700 bg-sky-500/10 px-4 py-2 text-sm text-sky-300 hover:bg-sky-500/20"
        >
          Search
        </button>
      </form>

      {!route.q.trim() ? (
        <Empty>Type something. An empty box is not a request for the whole atlas.</Empty>
      ) : hits.isLoading ? (
        <Loading what="the atlas" />
      ) : hits.error ? (
        <ErrorBox error={hits.error} />
      ) : (
        <>
          <p className="text-sm text-zinc-400">
            {hits.data!.total === 0 ? "No hits" : `${hits.data!.total} hit(s)`} for “
            <span className="text-zinc-200">{hits.data!.term}</span>”
          </p>

          {hits.data!.groups.map((group) => (
            <Panel
              key={group.kind}
              title={group.label}
              subtitle={`${group.count}${group.truncated ? "+ (page, not a total)" : ""}`}
            >
              <ul className="space-y-1">
                {group.rows.map((row, index) => {
                  const to = hitRoute(group.kind, row);
                  const label = hitLabel(row);
                  const detail = hitDetail(group.kind, row);
                  return (
                    <li key={`${group.kind}-${index}`} className="flex items-baseline gap-3">
                      <span className="min-w-0 flex-1 truncate text-sm">
                        {to ? <Link to={to}>{label}</Link> : <span className="text-zinc-300">{label}</span>}
                      </span>
                      {detail && (
                        <span className="shrink-0 font-mono text-[11px] text-zinc-600">{detail}</span>
                      )}
                    </li>
                  );
                })}
              </ul>
            </Panel>
          ))}

          {hits.data!.total > 0 && <Caveat tone="info">{hits.data!.recall_caveat}</Caveat>}
        </>
      )}
    </div>
  );
}
