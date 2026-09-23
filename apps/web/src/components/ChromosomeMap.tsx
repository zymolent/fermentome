/**
 * The karyotype: seventeen sequences drawn to scale, with gene density along each.
 *
 * This view exists because 6,600 rows is not a genome, it is a wall. A reader who wants to know
 * "where are the tRNAs" or "is chromosome XII as gene-dense as chromosome I" cannot get there by
 * paging a table, and no amount of sorting helps — the answer is spatial, so the display has to
 * be spatial too.
 *
 * Three decisions, each of which the obvious alternative gets wrong:
 *
 * **Drawn to scale.** Chromosome IV is 6.6x chromosome I. Tracks of equal width would make a
 * sparse large chromosome look denser than a packed small one, which is the exact comparison
 * this view is for. Every track's pixel width is its real length times one shared scale factor.
 *
 * **Density is binned server-side at a fixed number of bases**, not at a fixed number of bins
 * per chromosome. A fixed bin count would mean one bin is 2.3 kb on chrI and 15 kb on chrIV, and
 * the two tracks would stop being comparable at exactly the moment they are drawn side by side.
 *
 * **Every sequence is drawn, including the empty ones.** A karyotype that hides a chromosome
 * with no genes answers "which chromosomes have genes" when the reader asked "where are the
 * genes". In a partially loaded atlas that difference is the entire message, so the blocked
 * state draws all seventeen tracks, empty, and says why.
 *
 * Inline SVG rather than a chart library: this is a bespoke genomic coordinate system, not a bar
 * chart, and the project restricts charting to ECharts and sigma.js. Neither draws this.
 */

import type { KaryotypeRead, KaryotypeTrack } from "@/lib/api";

const VIEW_W = 1000;
const LABEL_W = 58;
const COUNT_W = 74;
const TRACK_X = LABEL_W + 6;
const TRACK_W = VIEW_W - TRACK_X - COUNT_W;
const ROW_H = 21;
const BAR_H = 12;
const RULER_H = 22;

/** 250 kb ticks: fine enough to locate a gene, coarse enough not to become a second track. */
const TICK_BASES = 250_000;

function formatBases(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(n % 1_000_000 === 0 ? 0 : 2)} Mb`;
  if (n >= 1_000) return `${Math.round(n / 1_000)} kb`;
  return `${n} bp`;
}

/**
 * The fill for one density bin.
 *
 * A continuous alpha ramp on one hue rather than a rainbow: the quantity is ordered, and an
 * ordered quantity on a categorical palette is read as categories. The floor of 0.18 is so that
 * a bin holding one gene is still visible against the track — the difference between "one gene
 * here" and "no genes here" is the one this view must never blur.
 */
function binFill(count: number, max: number): string {
  if (count <= 0) return "transparent";
  const t = max > 1 ? (count - 1) / (max - 1) : 1;
  return `rgba(56, 189, 248, ${(0.18 + 0.72 * t).toFixed(3)})`;
}

export function ChromosomeMap({
  data,
  selected,
  onSelect,
}: {
  data: KaryotypeRead;
  selected?: string;
  onSelect: (seqid: string | undefined) => void;
}) {
  const tracks = data.tracks;
  const longest = Math.max(1, ...tracks.map((t) => t.length));
  const scale = TRACK_W / longest;
  // One ramp across the whole figure, so a dark bin means the same thing on every track. Scaling
  // each track to its own maximum would make the emptiest chromosome look the densest.
  const peak = Math.max(1, ...tracks.map((t) => t.max_bin));
  const placed = tracks.reduce((sum, t) => sum + t.gene_count, 0);
  const height = tracks.length * ROW_H + RULER_H + 6;

  return (
    <div className="space-y-3">
      <svg
        viewBox={`0 0 ${VIEW_W} ${height}`}
        className="w-full"
        style={{ minHeight: 320 }}
        role="img"
        aria-label={`Gene density across ${tracks.length} sequences of ${data.reference_assembly}`}
      >
        {tracks.map((track, index) => (
          <Track
            key={track.seqid}
            track={track}
            y={index * ROW_H}
            scale={scale}
            peak={peak}
            available={data.available}
            binWidth={data.bin_width}
            selected={selected === track.seqid}
            onSelect={onSelect}
          />
        ))}

        {/* The ruler carries the scale claim. Without it "drawn to scale" is an assertion the
            reader has to take on trust; with it, chrIV's 1.5 Mb is checkable by eye. */}
        <g transform={`translate(0, ${tracks.length * ROW_H + 8})`}>
          <line
            x1={TRACK_X}
            y1={0}
            x2={TRACK_X + TRACK_W}
            y2={0}
            className="stroke-zinc-800"
            strokeWidth={1}
          />
          {Array.from({ length: Math.floor(longest / TICK_BASES) + 1 }, (_, i) => (
            <g key={i} transform={`translate(${TRACK_X + i * TICK_BASES * scale}, 0)`}>
              <line y1={0} y2={4} className="stroke-zinc-700" strokeWidth={1} />
              <text y={14} textAnchor="middle" className="fill-zinc-600 text-[9px]">
                {i === 0 ? "0" : formatBases(i * TICK_BASES)}
              </text>
            </g>
          ))}
        </g>
      </svg>

      <div className="flex flex-wrap items-center justify-between gap-3 text-[11px] text-zinc-500">
        <div className="flex items-center gap-2">
          {placed === 0 ? (
            <span className="text-zinc-600">
              nothing placed on any track — no density scale to show
            </span>
          ) : (
            <>
              <span>genes per {formatBases(data.bin_width)}</span>
              <span className="flex h-3 overflow-hidden rounded-sm">
                {[1, 2, 3, 4, 5].map((step) => (
                  <span
                    key={step}
                    className="block h-3 w-5"
                    style={{
                      background: binFill(((step - 1) / 4) * (peak - 1) + 1, peak),
                    }}
                  />
                ))}
              </span>
              <span className="font-mono tabular-nums">1 – {peak}</span>
            </>
          )}
        </div>
        <span>
          {data.reference_assembly} · lengths from the reference, not from the genes placed on it
        </span>
      </div>
    </div>
  );
}

function Track({
  track,
  y,
  scale,
  peak,
  available,
  binWidth,
  selected,
  onSelect,
}: {
  track: KaryotypeTrack;
  y: number;
  scale: number;
  peak: number;
  available: boolean;
  binWidth: number;
  selected: boolean;
  onSelect: (seqid: string | undefined) => void;
}) {
  const width = Math.max(2, track.length * scale);
  const binPx = Math.max(1, binWidth * scale);
  const mito = track.kind !== "nuclear";

  return (
    <g
      transform={`translate(0, ${y})`}
      onClick={() => onSelect(selected ? undefined : track.seqid)}
      className="cursor-pointer"
    >
      <title>
        {`${track.label} — ${formatBases(track.length)}${
          track.length_is_reference ? "" : " (lower bound: no reference length for this sequence)"
        }, ${track.gene_count.toLocaleString()} gene(s)${selected ? " — filtered" : ""}`}
      </title>

      {/* A full-row hit target, so the 85 kb mitochondrion is as clickable as chromosome IV. */}
      <rect
        x={0}
        y={0}
        width={VIEW_W}
        height={ROW_H}
        className={selected ? "fill-sky-500/10" : "fill-transparent hover:fill-zinc-800/40"}
      />

      <text
        x={LABEL_W}
        y={ROW_H / 2 + 3.5}
        textAnchor="end"
        className={`text-[10px] font-medium ${
          selected ? "fill-sky-300" : mito ? "fill-amber-400/70" : "fill-zinc-400"
        }`}
      >
        {track.label}
      </text>

      <rect
        x={TRACK_X}
        y={(ROW_H - BAR_H) / 2}
        width={width}
        height={BAR_H}
        rx={2.5}
        className={available ? "fill-zinc-900 stroke-zinc-800" : "fill-transparent stroke-zinc-800"}
        strokeWidth={1}
        strokeDasharray={available ? undefined : "3 3"}
      />

      {available &&
        track.bins.map((count, i) =>
          count > 0 ? (
            <rect
              key={i}
              x={TRACK_X + i * binWidth * scale}
              y={(ROW_H - BAR_H) / 2 + 1}
              width={binPx}
              height={BAR_H - 2}
              fill={binFill(count, peak)}
            />
          ) : null,
        )}

      {selected && (
        <rect
          x={TRACK_X - 1.5}
          y={(ROW_H - BAR_H) / 2 - 1.5}
          width={width + 3}
          height={BAR_H + 3}
          rx={3.5}
          className="fill-none stroke-sky-400"
          strokeWidth={1.5}
        />
      )}

      <text
        x={VIEW_W - 6}
        y={ROW_H / 2 + 3.5}
        textAnchor="end"
        className={`font-mono text-[10px] tabular-nums ${
          track.gene_count === 0 ? "fill-zinc-700" : "fill-zinc-500"
        }`}
      >
        {track.gene_count.toLocaleString()}
      </text>
    </g>
  );
}
