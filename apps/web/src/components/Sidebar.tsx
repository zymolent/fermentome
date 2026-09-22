/**
 * The left rail: one entry per section, grouped by what a reader is doing.
 *
 * The grouping is not cosmetic. It follows the atlas's own layers — what was read (Literature),
 * what it is about (Genomes, Annotations), what was measured (Data, Transcripts), what is
 * derived (Networks), and what is being decided (Evidence, Curation). A flat list of eleven
 * items would hide that the last two are governance, not content.
 */

import {
  Activity,
  BookOpen,
  ClipboardCheck,
  Database,
  Dna,
  FlaskConical,
  LayoutDashboard,
  Search,
  Share2,
  ShieldCheck,
  Tags,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { hrefFor, navigate, type Route } from "@/lib/router";

interface NavItem {
  label: string;
  icon: LucideIcon;
  route: Route;
  /** Route names this entry stays highlighted for, including its detail pages. */
  matches: Route["name"][];
  title: string;
}

interface NavGroup {
  label: string;
  items: NavItem[];
}

const GROUPS: NavGroup[] = [
  {
    label: "Overview",
    items: [
      {
        label: "Dashboard",
        icon: LayoutDashboard,
        route: { name: "dashboard" },
        matches: ["dashboard"],
        title: "What the atlas holds, and which parts are empty and why",
      },
      {
        label: "Search",
        icon: Search,
        route: { name: "search", q: "" },
        matches: ["search"],
        title: "Substring search across publications, genes, strains, products and reactions",
      },
    ],
  },
  {
    label: "Sources",
    items: [
      {
        label: "Literature",
        icon: BookOpen,
        route: { name: "literature" },
        matches: ["literature", "publication"],
        title: "5,164 papers: how the corpus narrowed and where it stalled",
      },
      {
        label: "Genomes",
        icon: Dna,
        route: { name: "genomes" },
        matches: ["genomes"],
        title: "References on disk, and the genetic code each compartment reads",
      },
      {
        label: "Annotations",
        icon: Tags,
        route: { name: "annotations" },
        matches: ["annotations", "gene"],
        title: "Genes, gene groups and their functional annotation",
      },
    ],
  },
  {
    label: "Measurements",
    items: [
      {
        label: "Data",
        icon: Database,
        route: { name: "data" },
        matches: ["data"],
        title: "Titers, yields and tolerances, with their comparability caveats",
      },
      {
        label: "Transcripts",
        icon: Activity,
        route: { name: "transcripts" },
        matches: ["transcripts"],
        title: "Sequencing studies and runs, split by what each can support",
      },
    ],
  },
  {
    label: "Derived",
    items: [
      {
        label: "Networks",
        icon: Share2,
        route: { name: "networks" },
        matches: ["networks", "route", "pathway"],
        title: "The reaction graph, and the enumerated route space over it",
      },
    ],
  },
  {
    label: "Governance",
    items: [
      {
        label: "Evidence",
        icon: ShieldCheck,
        route: { name: "evidence" },
        matches: ["evidence"],
        title: "Assertions and where each one's traceability chain breaks",
      },
      {
        label: "Curation",
        icon: ClipboardCheck,
        route: { name: "curation" },
        matches: ["curation"],
        title: "The proposal queue — read-only; accepting happens in `fermdb curate`",
      },
    ],
  },
];

export function Sidebar({ route }: { route: Route }) {
  return (
    <nav className="flex w-56 shrink-0 flex-col border-r border-zinc-800 bg-zinc-950">
      <div className="flex items-center gap-2 border-b border-zinc-800 px-4 py-4">
        <FlaskConical className="h-5 w-5 text-sky-400" />
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-zinc-100">fermdb</div>
          <div className="truncate text-[11px] text-zinc-500">isobutanol atlas</div>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto py-3">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            <div className="px-4 pb-1.5 text-[10px] font-semibold uppercase tracking-wider text-zinc-600">
              {group.label}
            </div>
            <ul>
              {group.items.map((item) => {
                const active = item.matches.includes(route.name);
                const Icon = item.icon;
                return (
                  <li key={item.label}>
                    <a
                      href={hrefFor(item.route)}
                      title={item.title}
                      onClick={(event) => {
                        if (event.metaKey || event.ctrlKey || event.button !== 0) return;
                        event.preventDefault();
                        navigate(item.route);
                      }}
                      className={`flex items-center gap-2.5 px-4 py-1.5 text-sm transition-colors ${
                        active
                          ? "border-l-2 border-sky-500 bg-sky-500/10 pl-[14px] font-medium text-sky-300"
                          : "border-l-2 border-transparent pl-[14px] text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                      }`}
                    >
                      <Icon className="h-4 w-4 shrink-0" />
                      <span className="truncate">{item.label}</span>
                    </a>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </div>

      <div className="border-t border-zinc-800 px-4 py-3 text-[10px] leading-relaxed text-zinc-600">
        Read-only. Curation writes go through{" "}
        <code className="text-zinc-500">fermdb curate</code>.
      </div>
    </nav>
  );
}
