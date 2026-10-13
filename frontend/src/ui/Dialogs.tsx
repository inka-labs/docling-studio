/** confirm() / prompt() / toast() that look like the rest of Studio. Call them from anywhere;
 *  <DialogHost/> (in App) draws them. */
import { useEffect, useRef, useState } from "react";

type Ask = {
  title: string;
  body?: string;
  confirm: string;
  danger?: boolean;
  input?: { value: string; placeholder?: string; secret?: boolean };
  resolve: (value: string | boolean | null) => void;
};

let show: (a: Ask) => void = () => {};
let notify: (text: string) => void = () => {};

export function confirm(title: string, opts: { body?: string; confirm?: string; danger?: boolean } = {}): Promise<boolean> {
  return new Promise((resolve) => show({ title, body: opts.body, confirm: opts.confirm ?? "OK", danger: opts.danger, resolve: (v) => resolve(v === true) }));
}

export function prompt(title: string, opts: { body?: string; value?: string; placeholder?: string; confirm?: string; secret?: boolean } = {}): Promise<string | null> {
  return new Promise((resolve) =>
    show({ title, body: opts.body, confirm: opts.confirm ?? "Save", input: { value: opts.value ?? "", placeholder: opts.placeholder, secret: opts.secret },
      resolve: (v) => resolve(typeof v === "string" ? v : null) }),
  );
}

export function toast(text: string) {
  notify(text);
}

export function DialogHost() {
  const [ask, setAsk] = useState<Ask | null>(null);
  const [value, setValue] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const okRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    show = (a) => {
      setValue(a.input?.value ?? "");
      setAsk(a);
    };
    let timer: number | undefined;
    notify = (text) => {
      setMessage(text);
      clearTimeout(timer);
      timer = window.setTimeout(() => setMessage(null), 2600);
    };
  }, []);

  useEffect(() => {
    if (ask) setTimeout(() => (ask.input ? inputRef.current?.select() : okRef.current?.focus()), 0);
  }, [ask]);

  const close = (result: string | boolean | null) => {
    ask?.resolve(result);
    setAsk(null);
  };

  return (
    <>
      {ask && (
        <div className="dialog-backdrop" onMouseDown={(e) => e.target === e.currentTarget && close(null)}
          onKeyDown={(e) => e.key === "Escape" && close(null)}>
          <form className="dialog" role="dialog" aria-modal aria-label={ask.title}
            onSubmit={(e) => {
              e.preventDefault();
              close(ask.input ? value : true);
            }}>
            <h2>{ask.title}</h2>
            {ask.body && <p className="muted" style={{ whiteSpace: "pre-wrap" }}>{ask.body}</p>}
            {ask.input && (
              <input ref={inputRef} type={ask.input.secret ? "password" : "text"} value={value} placeholder={ask.input.placeholder}
                onChange={(e) => setValue(e.target.value)} />
            )}
            <div className="actions">
              <button type="button" onClick={() => close(null)}>Cancel</button>
              <button ref={okRef} type="submit" className={ask.danger ? "danger" : "primary"} disabled={!!ask.input && !value.trim()}>
                {ask.confirm}
              </button>
            </div>
          </form>
        </div>
      )}
      {message && <div className="toast" role="status">{message}</div>}
    </>
  );
}
