/** docling-serve services to convert on (`docling convert-remote`). API keys go into the system
 *  keychain; the browser never gets them back. */
import { useEffect, useState } from "react";
import { api, changed, type Service } from "../api";
import { href } from "../router";
import { confirm, toast } from "../ui/Dialogs";

type Draft = { original?: string; name: string; url: string; api_key: string; keepKey: boolean; hasKey: boolean };

export default function Services() {
  const [services, setServices] = useState<Service[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [checks, setChecks] = useState<Record<string, { ok: boolean; message: string } | "checking">>({});

  const load = () => api.services().then(setServices).catch((e) => setError(e.message));
  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (!draft) return;
    setSaving(true);
    setFormError(null);
    try {
      const key = draft.keepKey ? null : draft.api_key;
      if (draft.original) await api.changeService(draft.original, { name: draft.name, url: draft.url, api_key: key });
      else await api.addService({ name: draft.name, url: draft.url, api_key: draft.api_key || undefined });
      setDraft(null);
      await load();
      changed();
      check(draft.name);
    } catch (e) {
      setFormError((e as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const check = async (name: string) => {
    setChecks((c) => ({ ...c, [name]: "checking" }));
    try {
      const result = await api.checkService(name);
      setChecks((c) => ({ ...c, [name]: result }));
    } catch (e) {
      setChecks((c) => ({ ...c, [name]: { ok: false, message: (e as Error).message } }));
    }
  };

  const remove = async (s: Service) => {
    if (!(await confirm(`Delete ${s.name}?`, { body: s.has_key ? "Its API key is removed from your keychain too." : undefined, confirm: "Delete", danger: true }))) return;
    await api.deleteService(s.name);
    toast(`Deleted ${s.name}`);
    load();
    changed();
  };

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Services</h1>
          <div className="lede">
            A <a href="https://github.com/docling-project/docling-serve" target="_blank" rel="noreferrer">docling-serve</a> service converts on another computer
            (a GPU server, say). Save it here once; <a href={href({ page: "tool", id: "convert-remote" })}>Convert on a server</a> sends documents to it.
            API keys are kept in your system keychain.
          </div>
        </div>
        {!draft && <button className="primary" onClick={() => setDraft({ name: "", url: "", api_key: "", keepKey: false, hasKey: false })}>Add service</button>}
      </div>
      {error && <div className="banner error">{error}</div>}

      {draft && (
        <form className="card" style={{ marginBottom: 14 }} onSubmit={(e) => { e.preventDefault(); save(); }}>
          <div className="card-head"><h2>{draft.original ? `Change ${draft.original}` : "Add a service"}</h2></div>
          <div className="card-body section-body" style={{ padding: 16 }}>
            <label className="field"><span className="field-label">Name</span>
              <input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} placeholder="gpu-box" autoFocus /></label>
            <label className="field"><span className="field-label">URL</span>
              <input value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} placeholder="http://localhost:5001" spellCheck={false} /></label>
            <div className="field full">
              <span className="field-label">API key <span className="field-flag">X-Api-Key</span></span>
              {draft.keepKey ? (
                <div className="row"><span className="muted">A key is saved in your keychain.</span>
                  <button type="button" className="small" onClick={() => setDraft({ ...draft, keepKey: false, api_key: "" })}>Replace or remove it</button></div>
              ) : (
                <input type="password" value={draft.api_key} onChange={(e) => setDraft({ ...draft, api_key: e.target.value })} autoComplete="off"
                  placeholder={draft.hasKey ? "Leave empty to remove the saved key" : "Leave empty if the service has no key"} />
              )}
            </div>
            {formError && <div className="banner error full" style={{ margin: 0 }}>{formError}</div>}
            <div className="row full">
              <button type="submit" className="primary" disabled={saving || !draft.name.trim() || !draft.url.trim()}>{saving ? "Saving…" : "Save"}</button>
              <button type="button" onClick={() => { setDraft(null); setFormError(null); }}>Cancel</button>
            </div>
          </div>
        </form>
      )}

      {services && services.length === 0 && !draft && (
        <div className="card empty">
          <h2>No services yet</h2>
          <p>Run one with <code>pip install docling-serve && docling-serve run</code> (it listens on port 5001), then add it here.</p>
        </div>
      )}
      {services && services.length > 0 && (
        <div className="card">
          <table className="list">
            <thead><tr><th>Name</th><th>URL</th><th>API key</th><th>Status</th><th /></tr></thead>
            <tbody>
              {services.map((s) => {
                const c = checks[s.name];
                return (
                  <tr key={s.name}>
                    <td><strong>{s.name}</strong></td>
                    <td className="mono small">{s.url}</td>
                    <td>{s.has_key ? <span className="badge ok">in keychain</span> : <span className="muted small">none</span>}</td>
                    <td className="small">
                      {c === "checking" ? <span className="muted">Checking…</span> : c ? <span style={{ color: c.ok ? "var(--ok)" : "var(--danger)" }}>{c.message}</span> : <button className="link" onClick={() => check(s.name)}>Check</button>}
                    </td>
                    <td className="nowrap" style={{ textAlign: "right" }}>
                      <button className="small" onClick={() => setDraft({ original: s.name, name: s.name, url: s.url, api_key: "", keepKey: s.has_key, hasKey: s.has_key })}>Change</button>{" "}
                      <button className="small danger ghost" onClick={() => remove(s)}>Delete</button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
