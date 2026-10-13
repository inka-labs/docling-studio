import { Component, Suspense, lazy, useEffect, useState, type ReactNode } from "react";
import { api, setUnauthorizedHandler } from "./api";
import { href, useRoute } from "./router";
import { DialogHost } from "./ui/Dialogs";
import { ThemeToggle } from "./ui/ThemeToggle";
// each page is loaded when first opened, so the first screen doesn't wait for the others
const ToolPage = lazy(() => import("./tools/ToolPage"));
const ToolsPage = lazy(() => import("./tools/Tools"));
const RunsPage = lazy(() => import("./runs/Runs"));
const RunPage = lazy(() => import("./runs/Run"));
const ModelsPage = lazy(() => import("./models/Models"));
const ServicesPage = lazy(() => import("./services/Services"));
const SettingsPage = lazy(() => import("./manage/Settings"));

type Summary = Awaited<ReturnType<typeof api.summary>>;

/** Counts for the nav: refreshed on navigation, when a page changes something, and every 5 s. */
function useSummary(routeKey: string) {
  const [summary, setSummary] = useState<Summary | null>(null);
  useEffect(() => {
    const load = () => api.summary().then(setSummary).catch(() => {});
    load();
    const timer = setInterval(load, 5000);
    window.addEventListener("studio:changed", load);
    return () => {
      clearInterval(timer);
      window.removeEventListener("studio:changed", load);
    };
  }, [routeKey]);
  return summary;
}

export default function App() {
  const route = useRoute();
  const [signedOut, setSignedOut] = useState(false);
  useEffect(() => setUnauthorizedHandler(() => setSignedOut(true)), []);
  const summary = useSummary(JSON.stringify(route));

  const section = route.page === "tool" ? "tools" : route.page === "run" ? "runs" : route.page;
  const live = (summary?.running ?? 0) + (summary?.queued ?? 0);
  const tabs = [
    { id: "convert", label: "Convert", to: href({ page: "convert" }) },
    { id: "tools", label: "Tools", to: href({ page: "tools" }) },
    { id: "runs", label: "Runs", to: href({ page: "runs" }), count: summary?.runs },
    { id: "models", label: "Models", to: href({ page: "models" }) },
    { id: "services", label: "Services", to: href({ page: "services" }), count: summary?.services || undefined },
    { id: "settings", label: "Settings", to: href({ page: "settings" }) },
  ];

  return (
    <div className="shell">
      <header className="topbar">
        <a className="brand" href={href({ page: "convert" })}>
          <img className="brand-mark" src="/favicon.svg" alt="" />
          <span className="brand-name">Docling Studio</span>
        </a>
        <nav aria-label="Main">
          {tabs.map((t) => (
            <a key={t.id} href={t.to} className={section === t.id ? "active" : ""} aria-current={section === t.id ? "page" : undefined}>
              {t.label}
              {t.count !== undefined && <span className="nav-count">{t.count}</span>}
              {t.id === "runs" && live > 0 && <span className="nav-live">● {live} active</span>}
            </a>
          ))}
        </nav>
        <span className="grow" />
        <ThemeToggle />
      </header>
      <main className="content">
        <PageBoundary key={route.page + ("id" in route ? route.id : "")}>
          <Suspense fallback={<div className="page"><p className="muted">Loading…</p></div>}>
            {signedOut ? (
              <div className="page">
                <div className="empty">
                  <h2>Not signed in</h2>
                  <p>Open <strong>Docling Studio</strong> again from Applications (Mac) or the Start menu (Windows); it signs you in.
                    If you started it from a terminal, use the sign-in link it printed.</p>
                </div>
              </div>
            ) : route.page === "convert" ? (
              <ToolPage key={"convert" + (route.from ?? "")} toolId="convert" from={route.from} />
            ) : route.page === "tool" ? (
              <ToolPage key={route.id + (route.from ?? "") + (route.file ?? "")} toolId={route.id} from={route.from} file={route.file} />
            ) : route.page === "tools" ? (
              <ToolsPage />
            ) : route.page === "runs" ? (
              <RunsPage />
            ) : route.page === "run" ? (
              <RunPage key={route.id} id={route.id} doc={route.doc} view={route.view} />
            ) : route.page === "models" ? (
              <ModelsPage />
            ) : route.page === "services" ? (
              <ServicesPage />
            ) : (
              <SettingsPage />
            )}
          </Suspense>
        </PageBoundary>
      </main>
      <DialogHost />
    </div>
  );
}

/** A page that throws shows what went wrong instead of a blank screen; the rest keeps working. */
class PageBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="page">
        <div className="banner error">
          <strong>This page ran into a problem.</strong>
          {"\n"}{this.state.error.message}
        </div>
        <button onClick={() => location.reload()}>Reload</button>
      </div>
    );
  }
}
