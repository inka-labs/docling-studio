/** Studio's HTTP API. Every call carries the session cookie (same origin); a 401 means the browser
 *  isn't signed in, which App shows as such. */

export type FieldType = "bool" | "int" | "float" | "string" | "path" | "choice";

export type Field = {
  name: string;
  kind: "argument" | "option";
  opts: string[];
  secondary_opts: string[];
  type: FieldType;
  choices: string[] | null;
  choice_labels?: Record<string, string>;
  suggestions?: string[];
  multiple: boolean;
  required: boolean;
  default: unknown;
  initial: unknown;
  help: string;
  is_flag: boolean;
  count: boolean;
  label: string;
  section: string;
  section_title: string;
  secret: boolean;
  /** when the option matters: other option -> values (true: when it's on) */
  when: Record<string, string[] | boolean> | null;
  /** an argument Studio fills from files: "sources" (many) or "file" (one) */
  input: "sources" | "file" | null;
};

export type Tool = {
  id: string;
  title: string;
  summary: string;
  command: string;
  help?: string;
  available: boolean;
  error?: string;
  service?: boolean;
  fields: Field[];
};

export type Schema = {
  tools: Tool[];
  versions: Record<string, string>;
  devices: string[];
  errors: Record<string, string>;
  elsewhere: Record<string, string>;
};

export type Input =
  | { kind: "upload"; id: string; name: string; size?: number }
  | { kind: "path"; path: string; name?: string; folder?: boolean }
  | { kind: "url"; url: string; name?: string }
  | { kind: "run"; run: string; file: string; name?: string };

export type Values = Record<string, unknown>;

export type RunRequest = { tool: string; values: Values; inputs: Record<string, Input[]>; service?: string | null; title?: string };

export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled" | "interrupted";

export type Run = {
  id: string;
  tool: string;
  tool_title: string;
  title: string;
  status: RunStatus;
  values: Values;
  had_secrets: string[];
  inputs: Record<string, Input[]>;
  service: string | null;
  command: string;
  created: string;
  started: string | null;
  ended: string | null;
  exit_code: number | null;
  error: string | null;
  progress: { done: number; failed: number; total: number | null; processed?: number; finished?: string[]; phase?: "starting" | "models" | "converting" | "saving" };
  outputs?: { count: number; size: number; documents: number };
  /** a job's (simple.py): what it was asked to save, and the files it saved */
  finish?: { kind: "simple"; formats: string[]; folder: string } | null;
  delivered?: Delivered[] | null;
};

export type Delivered = { document: string; format: string; path: string | null; size?: number; note: string | null };
export type Plan = { name: string; paid: boolean; features: Record<string, boolean>; message: string };
export type JobOptions = {
  name: string;
  tagline: string;
  formats: Record<string, string>;
  languages: Record<string, string>;
  scan: Record<string, string>;
  save_to: string;
  /** the same, shortened for showing (~/Documents/…) */
  save_to_label: string;
  plan: Plan;
  native_dialogs: boolean;
};
export type JobRequest = { inputs: Input[]; formats: string[]; scan: string; language: string; pages: string; pictures: "keep" | "describe" | "drop" };

export type OutputFile = { path: string; size: number; kind: string };
export type OutputDocument = { name: string; files: string[]; kinds: string[] };
export type RunDetail = Run & { files: { files: OutputFile[]; documents: OutputDocument[]; total_size: number }; file_base: string };

export type DocSummary = {
  name: string;
  version: string;
  origin: { mimetype?: string; filename?: string };
  pages: number;
  texts: number;
  labels: Record<string, number>;
  furniture: number;
  tables: number;
  pictures: number;
  key_value_items: number;
  form_items: number;
  groups: number;
};

export type DocTable = { index: number; label: string; pages: number[]; caption: string; rows: string[][]; header_rows: number[]; num_rows: number; num_cols: number };
export type DocPicture = {
  index: number;
  label: string;
  pages: number[];
  caption: string;
  src: string | null;
  classes: { name: string; confidence: number }[];
  description: string | null;
  other: unknown[];
};

export type Preset = { id: string; tool: string; name: string; values: Values; created: string; updated: string };
export type Service = { name: string; url: string; has_key: boolean; created: string; updated: string };
export type Model = { where: "docling" | "huggingface"; name: string; folder: string; path: string; size: number; docling: boolean };
export type Plugin = { name: string; value: string; package: string | null; version: string | null; builtin: boolean };
export type Settings = { max_parallel_runs: number; default_verbosity: number; keep_runs_days: number; save_to: string };
export type Version = { version: string; platform: string; bundled: boolean; home: string; autostart: { supported: boolean; enabled: boolean } };

let onUnauthorized: () => void = () => {};
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, path: string, body?: unknown, raw?: BodyInit): Promise<T> {
  const resp = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: raw ? { "Content-Type": "application/octet-stream" } : body !== undefined ? { "Content-Type": "application/json" } : undefined,
    body: raw ?? (body !== undefined ? JSON.stringify(body) : undefined),
  });
  if (resp.status === 401) onUnauthorized();
  if (!resp.ok) {
    let message = `${resp.status} ${resp.statusText}`;
    try {
      const data = await resp.json();
      if (data?.detail) message = typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(resp.status, message);
  }
  if (resp.status === 204) return undefined as T;
  return resp.json();
}

/** Tell the nav (counts) and other pages that something changed. */
export function changed() {
  window.dispatchEvent(new Event("studio:changed"));
}

export const api = {
  version: () => call<Version>("GET", "/api/version"),
  summary: () => call<{ runs: number; running: number; queued: number; services: number }>("GET", "/api/summary"),
  schema: (refresh = false) => call<Schema>("GET", `/api/schema${refresh ? "?refresh=true" : ""}`),
  preview: (req: RunRequest) => call<{ command: string | null; error: string | null }>("POST", "/api/preview", req),
  plugins: () => call<Plugin[]>("GET", "/api/plugins"),

  upload: (file: File) => call<Input & { kind: "upload"; size: number }>("POST", `/api/uploads?name=${encodeURIComponent(file.name)}`, undefined, file),
  discardUpload: (id: string) => call<void>("DELETE", `/api/uploads/${id}`),
  checkInput: (input: Input) => call<Input>("POST", "/api/inputs/check", input),

  runs: () => call<Run[]>("GET", "/api/runs"),
  run: (id: string) => call<RunDetail>("GET", `/api/runs/${id}`),
  startRun: (req: RunRequest) => call<Run>("POST", "/api/runs", req),
  renameRun: (id: string, title: string) => call<Run>("PATCH", `/api/runs/${id}`, { title }),
  deleteRun: (id: string) => call<void>("DELETE", `/api/runs/${id}`),
  cancelRun: (id: string) => call<Run>("POST", `/api/runs/${id}/cancel`),
  runLog: (id: string, offset: number) => call<{ text: string; offset: number; size: number; truncated: boolean }>("GET", `/api/runs/${id}/log?offset=${offset}`),
  runAgain: (id: string) => call<RunRequest & { had_secrets: string[] }>("GET", `/api/runs/${id}/again`),
  docSummary: (id: string, file: string) => call<DocSummary>("GET", `/api/runs/${id}/doc?file=${encodeURIComponent(file)}`),
  docTables: (id: string, file: string) => call<DocTable[]>("GET", `/api/runs/${id}/tables?file=${encodeURIComponent(file)}`),
  docPictures: (id: string, file: string) => call<DocPicture[]>("GET", `/api/runs/${id}/pictures?file=${encodeURIComponent(file)}`),
  docView: (id: string, file: string, split: boolean) => call<{ url: string }>("POST", `/api/runs/${id}/view`, { file, split }),
  reveal: (id: string, file?: string) => call<{ path: string }>("POST", `/api/runs/${id}/reveal`, file ? { file } : {}),

  presets: (tool: string) => call<Preset[]>("GET", `/api/presets?tool=${encodeURIComponent(tool)}`),
  savePreset: (tool: string, name: string, values: Values, id?: string) =>
    id ? call<Preset>("PUT", `/api/presets/${id}`, { tool, name, values }) : call<Preset>("POST", "/api/presets", { tool, name, values }),
  deletePreset: (id: string) => call<void>("DELETE", `/api/presets/${id}`),

  services: () => call<Service[]>("GET", "/api/services"),
  addService: (s: { name: string; url: string; api_key?: string }) => call<Service>("POST", "/api/services", s),
  changeService: (name: string, s: { name: string; url: string; api_key?: string | null }) => call<Service>("PUT", `/api/services/${encodeURIComponent(name)}`, s),
  deleteService: (name: string) => call<void>("DELETE", `/api/services/${encodeURIComponent(name)}`),
  checkService: (name: string) => call<{ ok: boolean; message: string; version?: unknown }>("POST", `/api/services/${encodeURIComponent(name)}/check`),

  models: () => call<{ models: Model[]; roots: Record<string, string>; total: number }>("GET", "/api/models"),
  deleteModel: (m: Model) => call<void>("DELETE", `/api/models/${m.where}/${encodeURIComponent(m.folder)}`),

  jobOptions: () => call<JobOptions>("GET", "/api/jobs/options"),
  startJob: (req: JobRequest) => call<Run>("POST", "/api/jobs", req),
  plan: () => call<Plan>("GET", "/api/plan"),
  openFile: (id: string, path: string) => call<{ ok: boolean }>("POST", `/api/runs/${id}/open`, { path }),
  showFile: (id: string, path: string) => call<{ ok: boolean }>("POST", `/api/runs/${id}/show`, { path }),
  chooseFiles: () => call<Input[]>("POST", "/api/choose/files"),
  chooseFolder: (purpose: "save_to" | "input") => call<{ path: string | null }>("POST", "/api/choose/folder", { purpose }),

  settings: () => call<Settings>("GET", "/api/settings"),
  saveSettings: (s: Partial<Settings>) => call<Settings>("PUT", "/api/settings", s),
  autostart: (enabled: boolean) => call<{ message: string; enabled: boolean }>("POST", "/api/autostart", { enabled }),
  quit: (force = false) => call<{ ok: boolean }>("POST", `/api/quit${force ? "?force=true" : ""}`),
};

/** The schema is read once per page load (it changes only when Docling is updated). */
let schemaPromise: Promise<Schema> | null = null;
export function loadSchema(refresh = false): Promise<Schema> {
  if (!schemaPromise || refresh) {
    schemaPromise = api.schema(refresh);
    schemaPromise.catch(() => (schemaPromise = null));
  }
  return schemaPromise;
}
