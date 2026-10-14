/** Where files are saved, start at login, the plan, Advanced mode, about, Quit. */
import { useEffect, useState } from "react";
import { api, type JobOptions, type Settings, type Version } from "../api";
import { BRAND } from "../brand";
import { href } from "../router";
import { confirm, toast } from "../ui/Dialogs";
import { setAdvanced, useAdvanced } from "./advanced";

export default function Preferences() {
  const [options, setOptions] = useState<JobOptions | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [version, setVersion] = useState<Version | null>(null);
  const [folder, setFolder] = useState("");
  const [quit, setQuit] = useState(false);
  const advanced = useAdvanced();

  useEffect(() => {
    api.jobOptions().then((o) => { setOptions(o); setFolder(o.save_to); }).catch(() => {});
    api.settings().then(setSettings).catch(() => {});
    api.version().then(setVersion).catch(() => {});
  }, []);

  const saveFolder = async (path: string) => {
    try {
      setSettings(await api.saveSettings({ save_to: path }));
      setOptions(await api.jobOptions());
      toast("Saved");
    } catch (e) {
      toast((e as Error).message);
    }
  };
  const chooseFolder = async () => {
    const { path } = await api.chooseFolder("save_to");
    if (path) {
      setFolder(path);
      setOptions(await api.jobOptions());
    }
  };
  const autostart = async (enabled: boolean) => {
    try {
      const r = await api.autostart(enabled);
      setVersion((v) => (v ? { ...v, autostart: { ...v.autostart, enabled: r.enabled } } : v));
    } catch (e) {
      toast((e as Error).message);
    }
  };
  const doQuit = async () => {
    if (!(await confirm(`Quit ${BRAND.name}?`, { confirm: "Quit" }))) return;
    try {
      await api.quit();
    } catch (e) {
      if (!(await confirm("A conversion is running", { body: "Quitting stops it.", confirm: "Stop it and quit", danger: true }))) return;
      await api.quit(true);
    }
    setQuit(true);
  };

  if (quit) return <div className="page simple"><div className="empty"><h2>{BRAND.name} has quit</h2><p>You can close this tab.</p></div></div>;

  return (
    <div className="page simple">
      <h1 style={{ marginBottom: 16 }}>Settings</h1>

      <div className="card">
        <div className="card-head"><h2>Saving</h2></div>
        <div className="card-body stack">
          <label className="field">
            <span className="field-label">Save converted files in</span>
            <div className="row" style={{ flexWrap: "nowrap" }}>
              <input value={folder} onChange={(e) => setFolder(e.target.value)} onBlur={() => folder !== options?.save_to && saveFolder(folder)} spellCheck={false} />
              {options?.native_dialogs && <button onClick={chooseFolder}>Choose…</button>}
            </div>
            <span className="field-help">A file with the same name is never overwritten: the new one gets “(2)” added.{settings?.save_to ? "" : " This is the default folder."}</span>
          </label>
        </div>
      </div>

      {version && (
        <div className="card">
          <div className="card-head"><h2>{BRAND.name}</h2><span className="badge">v{version.version}</span>{options && <span className="badge accent">{options.plan.name}</span>}</div>
          <div className="card-body stack">
            {options && <p className="muted" style={{ margin: 0 }}>{options.plan.message}</p>}
            {version.autostart.supported && (
              <div className="bool-row">
                <label className="switch"><input type="checkbox" checked={version.autostart.enabled} onChange={(e) => autostart(e.target.checked)} /><span /></label>
                <div><div className="field-label">Open {BRAND.name} when I log in</div><div className="field-help">It waits in the background, ready to convert.</div></div>
              </div>
            )}
            <div className="bool-row">
              <label className="switch"><input type="checkbox" checked={advanced} onChange={(e) => setAdvanced(e.target.checked)} /><span /></label>
              <div>
                <div className="field-label">Advanced mode</div>
                <div className="field-help">Every option Docling has, other tools (models, servers, exports) and full logs. {advanced && <a href={href({ page: "convert" })}>Open it</a>}</div>
              </div>
            </div>
            <div className="small muted">
              Documents are converted on this computer with <a href="https://docling.ai" target="_blank" rel="noreferrer">Docling</a> (MIT licence) and its models
              (Apache-2.0, CDLA-Permissive-2.0); nothing is sent anywhere unless you add a web address.
            </div>
            <div><button className="danger" onClick={doQuit}>Quit {BRAND.name}</button></div>
          </div>
        </div>
      )}
    </div>
  );
}
