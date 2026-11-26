import { useEffect, useState } from "react";

export type Route =
  | { page: "convert"; from?: string }
  | { page: "tools" }
  /** one tool's form; from: an earlier run to start from */
  | { page: "tool"; id: string; from?: string; file?: string }
  | { page: "runs" }
  | { page: "run"; id: string; doc?: string; view?: string }
  | { page: "models" }
  | { page: "services" }
  | { page: "settings" }
  /** the LPO lab: test set and experiments; one experiment; one document's review */
  | { page: "lpo" }
  | { page: "lpo-exp"; id: string }
  | { page: "lpo-doc"; id: string; exp?: string };

export function parse(hash: string): Route {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const qs = new URLSearchParams(query);
  const from = qs.get("from") ?? undefined;
  if (parts[0] === "tools" && parts[1]) {
    if (parts[1] === "convert") return { page: "convert", from };
    return { page: "tool", id: parts[1], from, file: qs.get("file") ?? undefined };
  }
  if (parts[0] === "tools") return { page: "tools" };
  if (parts[0] === "runs" && parts[1]) return { page: "run", id: parts[1], doc: qs.get("doc") ?? undefined, view: qs.get("view") ?? undefined };
  if (parts[0] === "runs") return { page: "runs" };
  if (parts[0] === "lpo" && parts[1] === "experiments" && parts[2]) return { page: "lpo-exp", id: parts[2] };
  if (parts[0] === "lpo" && parts[1] === "docs" && parts[2]) return { page: "lpo-doc", id: parts[2], exp: qs.get("exp") ?? undefined };
  if (parts[0] === "lpo") return { page: "lpo" };
  if (parts[0] === "models") return { page: "models" };
  if (parts[0] === "services") return { page: "services" };
  if (parts[0] === "settings") return { page: "settings" };
  return { page: "convert", from };
}

export function href(route: Route): string {
  const qs = new URLSearchParams();
  switch (route.page) {
    case "convert":
      if (route.from) qs.set("from", route.from);
      return `#/tools/convert${qs.size ? `?${qs}` : ""}`;
    case "tool":
      if (route.from) qs.set("from", route.from);
      if (route.file) qs.set("file", route.file);
      return `#/tools/${encodeURIComponent(route.id)}${qs.size ? `?${qs}` : ""}`;
    case "run":
      if (route.doc) qs.set("doc", route.doc);
      if (route.view) qs.set("view", route.view);
      return `#/runs/${route.id}${qs.size ? `?${qs}` : ""}`;
    case "lpo-exp":
      return `#/lpo/experiments/${encodeURIComponent(route.id)}`;
    case "lpo-doc":
      if (route.exp) qs.set("exp", route.exp);
      return `#/lpo/docs/${encodeURIComponent(route.id)}${qs.size ? `?${qs}` : ""}`;
    default:
      return `#/${route.page}`;
  }
}

export function navigate(route: Route, replace = false) {
  if (replace) history.replaceState(null, "", href(route));
  else window.location.hash = href(route);
  if (replace) window.dispatchEvent(new HashChangeEvent("hashchange"));
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const onChange = () => setRoute(parse(window.location.hash));
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return route;
}
