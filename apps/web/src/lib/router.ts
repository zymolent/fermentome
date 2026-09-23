/**
 * URL-driven navigation, History API plus a subscription.
 *
 * Every view is a URL so a gene, a study or a route can be bookmarked and sent to someone.
 * A routing library is more machinery than this needs; when it stops being enough, pages do not
 * have to change, only this file.
 */

import { useCallback, useSyncExternalStore } from "react";

export type Route =
  | { name: "dashboard" }
  | { name: "literature"; q?: string; family?: string; readable?: boolean }
  | { name: "publication"; id: string }
  | { name: "genomes" }
  | {
      name: "annotations";
      q?: string;
      seqid?: string;
      biotype?: string;
      assembly?: string;
      source?: string;
      strand?: string;
      order?: string;
      page?: number;
    }
  | { name: "gene"; id: string }
  | { name: "transcripts"; study?: string }
  | { name: "networks" }
  | { name: "route"; id: string }
  | { name: "pathway"; id: string }
  | { name: "data"; kind?: string }
  | { name: "strains"; q?: string; cls?: string }
  | { name: "strain"; id: string }
  | { name: "experiments"; q?: string }
  | { name: "experiment"; id: string }
  | { name: "products" }
  | { name: "product"; id: string }
  | { name: "compare"; kind: "strain" | "experiment"; ids: string[] }
  | { name: "evidence" }
  | { name: "curation" }
  | { name: "search"; q: string };

const listeners = new Set<() => void>();

function emit() {
  for (const listener of listeners) listener();
}

if (typeof window !== "undefined") {
  window.addEventListener("popstate", emit);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function snapshot(): string {
  return window.location.pathname + window.location.search;
}

export function parseRoute(href: string): Route {
  const url = new URL(href, window.location.origin);
  const parts = url.pathname.split("/").filter(Boolean);
  const params = url.searchParams;
  const head = parts[0];

  switch (head) {
    case undefined:
      return { name: "dashboard" };
    case "literature":
      if (parts[1] === "publications" && parts[2]) {
        return { name: "publication", id: decodeURIComponent(parts.slice(2).join("/")) };
      }
      return {
        name: "literature",
        q: params.get("q") ?? undefined,
        family: params.get("family") ?? undefined,
        readable: params.get("readable") === "1" ? true : undefined,
      };
    case "genomes":
      return { name: "genomes" };
    case "annotations":
      if (parts[1] === "genes" && parts[2]) {
        return { name: "gene", id: decodeURIComponent(parts.slice(2).join("/")) };
      }
      return {
        name: "annotations",
        q: params.get("q") ?? undefined,
        seqid: params.get("seqid") ?? undefined,
        biotype: params.get("biotype") ?? undefined,
        assembly: params.get("assembly") ?? undefined,
        source: params.get("source") ?? undefined,
        strand: params.get("strand") ?? undefined,
        order: params.get("order") ?? undefined,
        page: params.get("page") ? Number(params.get("page")) : undefined,
      };
    case "transcripts":
      return { name: "transcripts", study: params.get("study") ?? undefined };
    case "networks":
      if (parts[1] === "routes" && parts[2]) {
        return { name: "route", id: decodeURIComponent(parts.slice(2).join("/")) };
      }
      if (parts[1] === "pathways" && parts[2]) {
        return { name: "pathway", id: decodeURIComponent(parts.slice(2).join("/")) };
      }
      return { name: "networks" };
    case "data":
      return { name: "data", kind: params.get("kind") ?? undefined };
    case "strains":
      if (parts[1]) return { name: "strain", id: decodeURIComponent(parts.slice(1).join("/")) };
      return {
        name: "strains",
        q: params.get("q") ?? undefined,
        cls: params.get("class") ?? undefined,
      };
    case "experiments":
      if (parts[1]) return { name: "experiment", id: decodeURIComponent(parts.slice(1).join("/")) };
      return { name: "experiments", q: params.get("q") ?? undefined };
    case "products":
      if (parts[1]) return { name: "product", id: decodeURIComponent(parts.slice(1).join("/")) };
      return { name: "products" };
    case "compare":
      return {
        name: "compare",
        kind: params.get("kind") === "experiment" ? "experiment" : "strain",
        // Repeated `id`, never a comma-joined string: an atlas identifier is
        // `YAA:STRAIN:cen-pk113-7d`, and any separator you pick is one an id may one day carry.
        ids: params.getAll("id"),
      };
    case "evidence":
      return { name: "evidence" };
    case "curation":
      return { name: "curation" };
    case "search":
      return { name: "search", q: params.get("q") ?? "" };
    default:
      return { name: "dashboard" };
  }
}

export function hrefFor(route: Route): string {
  switch (route.name) {
    case "dashboard":
      return "/";
    case "literature": {
      const params = new URLSearchParams();
      if (route.q) params.set("q", route.q);
      if (route.family) params.set("family", route.family);
      if (route.readable) params.set("readable", "1");
      const text = params.toString();
      return `/literature${text ? `?${text}` : ""}`;
    }
    case "publication":
      return `/literature/publications/${encodeURIComponent(route.id)}`;
    case "genomes":
      return "/genomes";
    case "annotations": {
      // Every filter lives here rather than in component state, so a filtered view is a URL
      // someone can bookmark, reload and send to a collaborator. A facet rail whose selection
      // dies on refresh is a control, not a view.
      const params = new URLSearchParams();
      for (const [key, value] of [
        ["q", route.q],
        ["seqid", route.seqid],
        ["biotype", route.biotype],
        ["assembly", route.assembly],
        ["source", route.source],
        ["strand", route.strand],
        ["order", route.order],
        ["page", route.page && route.page > 1 ? String(route.page) : undefined],
      ] as const) {
        if (value) params.set(key, String(value));
      }
      const text = params.toString();
      return `/annotations${text ? `?${text}` : ""}`;
    }
    case "gene":
      return `/annotations/genes/${encodeURIComponent(route.id)}`;
    case "transcripts":
      return `/transcripts${route.study ? `?study=${encodeURIComponent(route.study)}` : ""}`;
    case "networks":
      return "/networks";
    case "route":
      return `/networks/routes/${encodeURIComponent(route.id)}`;
    case "pathway":
      return `/networks/pathways/${encodeURIComponent(route.id)}`;
    case "data":
      return `/data${route.kind ? `?kind=${encodeURIComponent(route.kind)}` : ""}`;
    case "strains": {
      const params = new URLSearchParams();
      if (route.q) params.set("q", route.q);
      if (route.cls) params.set("class", route.cls);
      const text = params.toString();
      return `/strains${text ? `?${text}` : ""}`;
    }
    case "strain":
      return `/strains/${encodeURIComponent(route.id)}`;
    case "experiments":
      return `/experiments${route.q ? `?q=${encodeURIComponent(route.q)}` : ""}`;
    case "experiment":
      return `/experiments/${encodeURIComponent(route.id)}`;
    case "products":
      return "/products";
    case "product":
      return `/products/${encodeURIComponent(route.id)}`;
    case "compare": {
      const params = new URLSearchParams();
      params.set("kind", route.kind);
      for (const id of route.ids) params.append("id", id);
      return `/compare?${params.toString()}`;
    }
    case "evidence":
      return "/evidence";
    case "curation":
      return "/curation";
    case "search":
      return `/search?q=${encodeURIComponent(route.q)}`;
  }
}

export function navigate(route: Route, replace = false): void {
  const href = hrefFor(route);
  if (replace) window.history.replaceState({}, "", href);
  else window.history.pushState({}, "", href);
  emit();
}

export function useRoute(): Route {
  const href = useSyncExternalStore(subscribe, snapshot, () => "/");
  return parseRoute(new URL(href, window.location.origin).toString());
}

/**
 * Props for an anchor that navigates without a reload, but is still a real link.
 *
 * `href` is set so middle-click, ctrl-click and "copy link address" all work; only a plain
 * left-click is intercepted. A `<div onClick>` would look identical and break all three.
 */
export function useLink(route: Route) {
  const href = hrefFor(route);
  const onClick = useCallback(
    (event: React.MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      event.preventDefault();
      navigate(route);
    },
    [href],
  );
  return { href, onClick };
}
