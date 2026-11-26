/** The LPO lab's API (backend: docling_studio/lpo/api.py). */
import { call } from "../api";

export type FieldKind = "text" | "date" | "number" | "choice";
export type FieldDef = { name: string; label: string; kind: FieldKind; group: "header" | "parties" | "totals" };
export type ColumnDef = { name: string; label: string; kind: FieldKind };
export type LpoSchema = { fields: FieldDef[]; lines: ColumnDef[]; document_types: Record<string, string> };

export type Line = { item_code: string | null; barcode: string | null; description: string | null; uom: string | null; quantity: number | null; unit_price: number | null; amount: number | null };
export type LpoRecord = { fields: Record<string, string | number | null>; lines: Line[] };
export type Label = LpoRecord & { not_lpo: boolean; notes: string; from_experiment: string | null; saved: string };

export type Config = { extractor: "rules" | "vlm"; ocr: "auto" | "off" | "full"; ocr_engine: string; table_mode: "accurate" | "fast"; straighten: boolean; vlm_model: string };

export type Client = { name: string; documents: number; newest: string; on: boolean };
export type Job = { job: string | null; status: "idle" | "running" | "failed" | "stopped"; done: number; total: number; message: string; error: string | null };
export type TestsetSummary = {
  documents: number; holdout: number; labelled_holdout: number; excluded: number; pages: number; labelled: number; updated: string | null;
  kinds: { digital: number; scan: number; image: number };
  clients: { name: string; documents: number; digital?: number; scan?: number; image?: number }[];
};
export type Overview = {
  source: { bucket: string; listed: string | null; clients_off: string[] | null };
  clients: Client[];
  testset: TestsetSummary;
  job: Job;
  schema: LpoSchema;
  checks: Record<string, string>;
  options: { choices: Record<string, (string | boolean)[]>; defaults: Config; ocr_engines: Record<string, string> };
  mapper: number;
};

export type Checks = Record<string, boolean>;
export type GroupScore = { documents: number; ok_rate: number | null; lines_found: number | null; lpo_number: number | null };
export type Summary = {
  documents: number; errors: number; ok_rate: number | null;
  checks: Record<string, number | null>; check_counts?: Record<string, number>;
  fill: Record<string, number | null>; lines_found: number | null;
  lines_from?: Record<string, number>;
  seconds: { convert_mean: number | null; converted: number };
  labelled: number; perfect_rate: number | null;
  accuracy: null | {
    fields: number | null; line_recall: number | null; line_precision: number | null; line_numbers: number | null;
    by_field: Record<string, { right: number; of: number; rate: number | null }>;
  };
  by_kind: Record<string, GroupScore>; by_client?: Record<string, GroupScore>; by_split?: Record<string, GroupScore>;
};
export type ExperimentStatus = "queued" | "running" | "finished" | "stopped" | "failed" | "interrupted";
export type Experiment = {
  id: string; name: string; config: Config; conv: string; subset: string; limit: number | null; split?: Split; docs: number;
  status: ExperimentStatus; created: string; started: string | null; ended: string | null; notes: string;
  progress: { done: number; failed: number; total: number; current?: string | null };
  summary: Summary; stale_mapper?: boolean;
};

export type DocRow = {
  id: string; key: string; client: string; kind: "digital" | "scan" | "image"; pages: number; size: number; modified: string;
  excluded: boolean; labelled: boolean; split: "dev" | "holdout";
  result?: { error: string | null; ok: boolean | null; checks: Checks | null; lines: number; lpo_number: string | null; document_type: string | null };
};
export type Split = "dev" | "holdout" | "both";
export type Layout = {
  id: string; kind: string; kinds: Record<string, number>; words: string[]; surveyed: number; in_set: number;
  clients: Record<string, number>; examples: { id: string; in_set: boolean; key: string }[]; addable: string[]; gap: boolean;
};
export type Layouts = { layouts: Layout[]; surveyed: number; fingerprinted: number; updated: string | null };
export type Box = { page: number; box: [number, number, number, number] };
export type Result = {
  doc: string; conv: string; record?: LpoRecord; where?: Record<string, Box>; checks?: Checks; lines_from?: string;
  cached?: boolean; seconds?: { convert: number | null; map: number }; error: string | null; trace?: string;
  comparison?: { fields: Record<string, boolean>; lines: { predicted: number; true: number; matched: number; numbers_right: number; numbers_total: number }; perfect: boolean };
};
export type DocDetail = DocRow & { file: string; label: Label | null; orientation: number[] | null; text_chars?: number };

const enc = encodeURIComponent;

export const lpo = {
  overview: () => call<Overview>("GET", "/api/lpo/overview"),
  saveSource: (changes: { bucket?: string; clients_off?: string[] }) => call<Overview["source"]>("PUT", "/api/lpo/source", changes),
  refreshListing: () => call<Job>("POST", "/api/lpo/listing"),
  buildTestset: (size: number) => call<Job>("POST", "/api/lpo/testset", { size }),
  stopJob: () => call<Job>("POST", "/api/lpo/job/stop"),

  docs: (exp?: string) => call<DocRow[]>("GET", `/api/lpo/docs${exp ? `?exp=${enc(exp)}` : ""}`),
  doc: (id: string) => call<DocDetail>("GET", `/api/lpo/docs/${enc(id)}`),
  excludeDoc: (id: string, excluded: boolean) => call<DocRow>("PATCH", `/api/lpo/docs/${enc(id)}`, { excluded }),
  pageUrl: (id: string, page: number, straight = true) => `/api/lpo/docs/${enc(id)}/pages/${page}${straight ? "" : "?straight=false"}`,
  fileUrl: (id: string) => `/api/lpo/docs/${enc(id)}/file`,
  saveLabel: (id: string, label: LpoRecord & { not_lpo?: boolean; notes?: string; from_experiment?: string | null }) =>
    call<Label & { checks: Checks }>("PUT", `/api/lpo/docs/${enc(id)}/label`, label),
  deleteLabel: (id: string) => call<void>("DELETE", `/api/lpo/docs/${enc(id)}/label`),
  check: (record: LpoRecord) => call<{ record: LpoRecord; checks: Checks }>("POST", "/api/lpo/check", record),

  experiments: () => call<Experiment[]>("GET", "/api/lpo/experiments"),
  experiment: (id: string) => call<Experiment>("GET", `/api/lpo/experiments/${enc(id)}`),
  createExperiment: (req: { name?: string; config: Partial<Config>; subset: string; split?: Split; limit?: number | null; notes?: string }) =>
    call<Experiment>("POST", "/api/lpo/experiments", req),
  renameExperiment: (id: string, changes: { name?: string; notes?: string }) => call<Experiment>("PATCH", `/api/lpo/experiments/${enc(id)}`, changes),
  deleteExperiment: (id: string) => call<void>("DELETE", `/api/lpo/experiments/${enc(id)}`),
  stopExperiment: (id: string) => call<Experiment>("POST", `/api/lpo/experiments/${enc(id)}/stop`),
  resumeExperiment: (id: string) => call<Experiment>("POST", `/api/lpo/experiments/${enc(id)}/resume`),
  remapExperiment: (id: string) => call<Experiment & { remapped: number }>("POST", `/api/lpo/experiments/${enc(id)}/remap`),
  experimentLog: (id: string, offset: number) => call<{ text: string; offset: number; size: number }>("GET", `/api/lpo/experiments/${enc(id)}/log?offset=${offset}`),
  result: (exp: string, doc: string) => call<Result>("GET", `/api/lpo/experiments/${enc(exp)}/docs/${enc(doc)}`),
  exportUrl: (id: string) => `/api/lpo/experiments/${enc(id)}/export`,

  survey: (per_client: number) => call<Job>("POST", "/api/lpo/survey", { per_client }),
  layouts: () => call<Layouts>("GET", "/api/lpo/survey/layouts"),
  thumbUrl: (id: string) => `/api/lpo/survey/thumbs/${enc(id)}`,
  addLayout: (id: string, count: number) => call<{ added: string[] }>("POST", `/api/lpo/survey/layouts/${enc(id)}/add`, { count }),
};

export const SPLITS: Record<Split, string> = { dev: "Working set (4 in 5)", holdout: "Held-out set (1 in 5)", both: "Both" };

/** 0.873 -> "87%"; null -> "–". */
export function pct(x: number | null | undefined, digits = 0): string {
  return x == null ? "–" : `${(x * 100).toFixed(digits)}%`;
}

export function describeConfig(c: Config, engines: Record<string, string> = {}): string {
  if (c.extractor === "vlm") return `VLM (${c.vlm_model === "nuextract" ? "NuExtract 2B" : "Granite Vision"})${c.straighten ? " · straightened" : ""}`;
  const ocr = c.ocr === "off" ? "no OCR" : `OCR ${c.ocr}${c.ocr_engine !== "auto" ? ` · ${engines[c.ocr_engine] ?? c.ocr_engine}` : ""}`;
  return `Rules · ${ocr} · tables ${c.table_mode}${c.straighten ? " · straightened" : ""}`;
}

export const SUBSETS: Record<string, string> = {
  all: "Whole test set",
  digital: "Digital PDFs only",
  scans: "Scans and photos only",
  labelled: "Labelled documents only",
};

export const KIND_LABEL: Record<string, string> = { digital: "Digital", scan: "Scan", image: "Photo" };
