/** Every Docling command Studio can run, read from the installed Docling. */
import { useEffect, useState } from "react";
import { loadSchema, type Schema } from "../api";
import { href } from "../router";

export default function Tools() {
  const [schema, setSchema] = useState<Schema | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  useEffect(() => {
    loadSchema().then(setSchema).catch((e) => setError(e.message));
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      setSchema(await loadSchema(true));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRefreshing(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div className="grow">
          <h1>Tools</h1>
          <div className="lede">
            Each of Docling's command-line tools, with every option the installed version has. Studio reads the options from Docling itself,
            so new ones show up after an update.
          </div>
        </div>
        <button onClick={refresh} disabled={refreshing}>{refreshing ? "Reading…" : "Read Docling's options again"}</button>
      </div>
      {error && <div className="banner error">{error}</div>}
      {!schema && !error && <p className="muted">Reading Docling's options…</p>}
      {schema && (
        <>
          {Object.entries(schema.errors).map(([program, message]) => (
            <div className="banner warn" key={program}><strong>{program}</strong> couldn't be loaded: {message}</div>
          ))}
          <div className="tool-cards">
            {schema.tools.map((t) => (
              <a key={t.id} className="card tool-card" href={href(t.id === "convert" ? { page: "convert" } : { page: "tool", id: t.id })}>
                <div className="row">
                  <h2 style={{ margin: 0 }}>{t.title}</h2>
                  <span className="grow" />
                  {t.available ? <span className="badge">{t.fields.length} options</span> : <span className="badge danger">unavailable</span>}
                </div>
                <code>{t.command}</code>
                <div className="muted">{t.available ? t.summary : t.error}</div>
              </a>
            ))}
            {Object.entries(schema.elsewhere).map(([command, where]) => (
              <div key={command} className="card tool-card" style={{ cursor: "default" }}>
                <h2 style={{ margin: 0 }}>View a document</h2>
                <code>{command}</code>
                <div className="muted">{where}</div>
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
