/** Studio's settings, what's installed (Docling's packages, accelerators, plugins), start at login
 *  and Quit. */
import { Fragment, useEffect, useState } from "react";
import { api, loadSchema, type Plugin, type Schema, type Settings as S, type Version } from "../api";
import { confirm, toast } from "../ui/Dialogs";

export default function Settings() {
  const [settings, setSettings] = useState<S | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [schema, setSchema] = useState<Schema | null>(null);
  const [plugins, setPlugins] = useState<Plugin[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [quitting, setQuitting] = useState(false);

  useEffect(() => {
    api.settings().then(setSettings).catch((e) => setError(e.message));
    api.version().then(setVersion).catch(() => {});
    loadSchema().then(setSchema).catch(() => {});
    api.plugins().then(setPlugins).catch(() => setPlugins([]));
  }, []);

  const change = async (patch: Partial<S>) => {
    try {
      setSettings(await api.saveSettings(patch));
      toast("Saved");
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const autostart = async (enabled: boolean) => {
    try {
      const r = await api.autostart(enabled);
      setVersion((v) => (v ? { ...v, autostart: { ...v.autostart, enabled: r.enabled } } : v));
      toast(r.message);
    } catch (e) {
      toast((e as Error).message);
    }
  };

  const quit = async () => {
    if (!(await confirm("Quit Docling Studio?", { body: "Open it again from Applications or the Start menu.", confirm: "Quit" }))) return;
    try {
      await api.quit();
    } catch (e) {
      if (!(await confirm("Runs are in progress", { body: `${(e as Error).message}\n\nQuitting stops them.`, confirm: "Stop them and quit", danger: true }))) return;
      await api.quit(true);
    }
    setQuitting(true);
  };

  if (quitting) return <div className="page"><div className="empty"><h2>Docling Studio has quit</h2><p>You can close this tab.</p></div></div>;

  return (
    <div className="page">
      <div className="page-head"><div className="grow"><h1>Settings</h1></div></div>
      {error && <div className="banner error">{error}</div>}

      {settings && (
        <div className="card">
          <div className="card-head"><h2>Runs</h2></div>
          <div className="card-body section-body" style={{ padding: 16 }}>
            <label className="field">
              <span className="field-label">Runs at the same time</span>
              <select value={settings.max_parallel_runs} onChange={(e) => change({ max_parallel_runs: Number(e.target.value) })}>
                {[1, 2, 3, 4, 6, 8].map((n) => <option key={n} value={n}>{n}</option>)}
              </select>
              <span className="field-help">Others wait their turn. Each conversion loads its own models, so more at once mostly needs more memory.</span>
            </label>
            <label className="field">
              <span className="field-label">Log detail for new runs</span>
              <select value={settings.default_verbosity} onChange={(e) => change({ default_verbosity: Number(e.target.value) })}>
                <option value={0}>Quiet: warnings and errors (Docling's default)</option>
                <option value={1}>Info (-v): what Docling is doing</option>
                <option value={2}>Debug (-vv): everything</option>
              </select>
              <span className="field-help">Each run's form can change it (Debug & profiling › Log detail).</span>
            </label>
            <label className="field">
              <span className="field-label">Delete finished runs after</span>
              <select value={settings.keep_runs_days} onChange={(e) => change({ keep_runs_days: Number(e.target.value) })}>
                <option value={0}>Never</option>
                {[7, 30, 90, 365].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
              <span className="field-help">Checked when Studio starts. Runs are in {version?.home ?? "~/.docling-studio"}/runs.</span>
            </label>
          </div>
        </div>
      )}

      {schema && (
        <div className="card">
          <div className="card-head"><h2>Docling on this computer</h2></div>
          <div className="card-body stack">
            <dl className="kv">
              {Object.entries(schema.versions).map(([pkg, v]) => (<Fragment key={pkg}><dt>{pkg}</dt><dd className="mono">{v}</dd></Fragment>))}
              <dt>Accelerators</dt><dd>{schema.devices.join(", ")} <span className="muted small">(--device auto picks the fastest)</span></dd>
            </dl>
            <div>
              <h3>Plugins</h3>
              {plugins === null ? <p className="muted small">Looking…</p> : (
                <table className="list">
                  <tbody>
                    {plugins.map((p) => (
                      <tr key={p.name}>
                        <td className="mono small">{p.name}</td>
                        <td className="small">{p.package} {p.version}</td>
                        <td>{p.builtin ? <span className="badge">built in</span> : <span className="badge warn">third party: needs --allow-external-plugins</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              <p className="muted small" style={{ marginTop: 6 }}>Third-party plugins add OCR, layout or table engines; install them into Studio's environment and they show up here.</p>
            </div>
          </div>
        </div>
      )}

      {version && (
        <div className="card">
          <div className="card-head"><h2>Docling Studio</h2><span className="badge">v{version.version}</span></div>
          <div className="card-body stack">
            {version.autostart.supported && (
              <div className="bool-row">
                <label className="switch">
                  <input type="checkbox" checked={version.autostart.enabled} onChange={(e) => autostart(e.target.checked)} />
                  <span />
                </label>
                <div>
                  <div className="field-label">Start Docling Studio when I log in</div>
                  <div className="field-help">In the background, so it's ready when you open it.</div>
                </div>
              </div>
            )}
            <div className="small muted">Studio keeps its runs, presets and settings in <code>{version.home}</code>. API keys are in your system keychain under “docling-studio”.</div>
            <div><button className="danger" onClick={quit}>Quit Docling Studio</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
