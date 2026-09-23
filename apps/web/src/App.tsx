/**
 * The shell: sidebar, a health banner, and the route switch.
 *
 * The health check runs once at the top and, when the atlas is unreachable, replaces the page
 * rather than letting each panel render its own error. Eleven identical "backend unreachable"
 * boxes is worse than one, and the API's 503 already says which file it looked for.
 */

import { useQuery } from "@tanstack/react-query";

import { Sidebar } from "@/components/Sidebar";
import { ErrorBox } from "@/components/ui";
import { AnnotationsPage, GenePage } from "@/pages/AnnotationsPage";
import { CurationPage } from "@/pages/CurationPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DataPage } from "@/pages/DataPage";
import { EvidencePage } from "@/pages/EvidencePage";
import { GenomesPage } from "@/pages/GenomesPage";
import { LiteraturePage } from "@/pages/LiteraturePage";
import { NetworksPage } from "@/pages/NetworksPage";
import { PublicationPage } from "@/pages/PublicationPage";
import { PathwayPage, RoutePage } from "@/pages/RoutePage";
import { SearchPage } from "@/pages/SearchPage";
import { TranscriptsPage } from "@/pages/TranscriptsPage";
import { api } from "@/lib/api";
import { useRoute } from "@/lib/router";

function Body() {
  const route = useRoute();

  switch (route.name) {
    case "dashboard":
      return <DashboardPage />;
    case "literature":
      return <LiteraturePage route={route} />;
    case "publication":
      return <PublicationPage id={route.id} />;
    case "genomes":
      return <GenomesPage />;
    case "annotations":
      return <AnnotationsPage route={route} />;
    case "gene":
      return <GenePage id={route.id} />;
    case "transcripts":
      return <TranscriptsPage route={route} />;
    case "networks":
      return <NetworksPage />;
    case "route":
      return <RoutePage id={route.id} />;
    case "pathway":
      return <PathwayPage id={route.id} />;
    case "data":
      return <DataPage route={route} />;
    case "evidence":
      return <EvidencePage />;
    case "curation":
      return <CurationPage />;
    case "search":
      return <SearchPage route={route} />;
  }
}

export function App() {
  const route = useRoute();
  const health = useQuery({ queryKey: ["health"], queryFn: api.health, retry: 0 });

  return (
    <div className="flex h-full">
      <Sidebar route={route} />
      <div className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <main className="mx-auto w-full max-w-7xl flex-1 px-8 py-8">
          {health.isError ? (
            <ErrorBox error={health.error} />
          ) : health.data && !health.data.ok ? (
            <ErrorBox error={new Error(`no atlas at ${health.data.atlas}`)} />
          ) : (
            <Body />
          )}
        </main>
        {health.data?.ok && (
          <footer className="border-t border-zinc-900 px-8 py-3 text-[11px] text-zinc-600">
            <span className="font-mono">{health.data.atlas}</span>
            <span className="mx-2 text-zinc-800">·</span>
            {health.data.size_bytes ? `${(health.data.size_bytes / 1e6).toFixed(0)} MB` : ""}
            <span className="mx-2 text-zinc-800">·</span>
            read-only ({health.data.writable_endpoints} write endpoints)
          </footer>
        )}
      </div>
    </div>
  );
}
