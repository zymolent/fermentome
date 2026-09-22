/**
 * The reaction graph, rendered with sigma.js over a ForceAtlas2 layout.
 *
 * Two rendering decisions carry meaning rather than taste.
 *
 * **Compartment is colour, not position.** A force layout positions by connectivity, so using
 * position for compartment would produce a picture that disagrees with the layout whenever a
 * reaction bridges two compartments — and bridging reactions are exactly the interesting ones
 * here. Colour is honest at every layout step; a drawn container would not be.
 *
 * **Cofactors are drawn smaller and dimmer.** NADH touches most reactions in the graph, so at
 * equal weight it becomes a hub that dominates the layout and says nothing. They stay visible
 * because a route's cofactor balance is the whole question — just not at the same weight as a
 * pathway intermediate.
 *
 * `graphology` and `sigma` are the only graph dependencies, per PLAN.md P.1's rule of one
 * network renderer chosen once.
 */

import { useEffect, useRef } from "react";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import Sigma from "sigma";

import type { ReactionGraph as GraphData } from "@/lib/api";

/** Compartment colours. Mitochondrial compartments share a hue family deliberately. */
const COMPARTMENT_COLOR: Record<string, string> = {
  cytosol: "#38bdf8",
  mitochondrial_matrix: "#f59e0b",
  mitochondrial_inner_membrane: "#fb923c",
  mitochondrial_ims: "#fbbf24",
  peroxisome: "#a78bfa",
  nucleus: "#f472b6",
  endoplasmic_reticulum: "#34d399",
  vacuole: "#94a3b8",
  extracellular: "#64748b",
};

const METABOLITE_COLOR = "#e4e4e7";
const COFACTOR_COLOR = "#52525b";

export function ReactionGraphView({
  data,
  onSelect,
  height = 560,
}: {
  data: GraphData;
  onSelect?: (id: string) => void;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);

  useEffect(() => {
    if (!container.current) return;

    const graph = new Graph({ multi: true });

    for (const node of data.nodes) {
      const isReaction = node.kind === "reaction";
      graph.addNode(node.id, {
        label: node.label,
        // Seeded at random then relaxed by ForceAtlas2; identical seeds would leave every node
        // at the origin and the layout would never separate them.
        x: Math.random(),
        y: Math.random(),
        size: isReaction ? 7 : node.is_cofactor ? 3 : 5,
        color: isReaction
          ? (COMPARTMENT_COLOR[node.compartment ?? ""] ?? "#71717a")
          : node.is_cofactor
            ? COFACTOR_COLOR
            : METABOLITE_COLOR,
        // Sigma v3 ships one node program, "circle". A "square" type needs @sigma/node-square
        // registered, and asking for an unregistered program throws at render and blanks the
        // panel. Reaction and metabolite are already distinguished by size and colour, so the
        // second shape is not worth a dependency.
        nodeKind: node.kind,
        compartment: node.compartment,
      });
    }

    for (const [index, edge] of data.edges.entries()) {
      if (!graph.hasNode(edge.source) || !graph.hasNode(edge.target)) continue;
      graph.addEdgeWithKey(`e${index}`, edge.source, edge.target, {
        size: 1,
        color: edge.role === "substrate" ? "#3f3f46" : "#52525b",
        type: "arrow",
      });
    }

    forceAtlas2.assign(graph, {
      iterations: 220,
      settings: {
        ...forceAtlas2.inferSettings(graph),
        gravity: 1.4,
        scalingRatio: 22,
        // Bigger nodes push harder, so a reaction does not end up buried under its own
        // metabolites.
        adjustSizes: true,
      },
    });

    const renderer = new Sigma(graph, container.current, {
      renderLabels: true,
      labelColor: { color: "#a1a1aa" },
      labelSize: 11,
      labelDensity: 0.5,
      labelGridCellSize: 120,
      defaultEdgeType: "arrow",
      minCameraRatio: 0.1,
      maxCameraRatio: 4,
    });
    sigmaRef.current = renderer;

    if (onSelect) {
      renderer.on("clickNode", ({ node }) => onSelect(node));
    }

    return () => {
      renderer.kill();
      sigmaRef.current = null;
    };
  }, [data, onSelect]);

  const compartments = data.compartments.filter((c) => c in COMPARTMENT_COLOR);

  return (
    <div>
      <div
        ref={container}
        style={{ height }}
        className="w-full rounded border border-zinc-800 bg-zinc-950"
      />
      <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2 text-[11px] text-zinc-500">
        {compartments.map((compartment) => (
          <span key={compartment} className="inline-flex items-center gap-1.5">
            <span
              className="h-2.5 w-2.5 rounded-sm"
              style={{ background: COMPARTMENT_COLOR[compartment] }}
            />
            {compartment}
          </span>
        ))}
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: METABOLITE_COLOR }} />
          metabolite
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2 w-2 rounded-full" style={{ background: COFACTOR_COLOR }} />
          cofactor (drawn smaller: it touches most reactions)
        </span>
      </div>
      <p className="mt-2 text-[11px] leading-relaxed text-zinc-600">{data.note}</p>
    </div>
  );
}
