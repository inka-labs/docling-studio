/** File-type badges: the colours people know Word, Excel and PDF files by. */
export const FORMAT_INFO: Record<string, { ext: string; color: string; note: string }> = {
  word: { ext: "DOCX", color: "#2b579a", note: "Edit in Word, Pages or Google Docs" },
  excel: { ext: "XLSX", color: "#217346", note: "Every table, one sheet each" },
  csv: { ext: "CSV", color: "#0f766e", note: "Every table as its own file" },
  markdown: { ext: "MD", color: "#5b4bb7", note: "For notes apps and AI chat tools" },
  text: { ext: "TXT", color: "#5f6b7a", note: "Just the words" },
  html: { ext: "HTML", color: "#c75c14", note: "Opens in any browser" },
};

const BY_EXT: Record<string, string> = {
  pdf: "#c4302b", docx: "#2b579a", doc: "#2b579a", xlsx: "#217346", xls: "#217346", csv: "#217346",
  pptx: "#c55a11", ppt: "#c55a11", png: "#7a4fb5", jpg: "#7a4fb5", jpeg: "#7a4fb5", tif: "#7a4fb5", tiff: "#7a4fb5",
  html: "#c75c14", htm: "#c75c14", md: "#5b4bb7", txt: "#5f6b7a",
};

export function FileIcon({ name, folder }: { name: string; folder?: boolean }) {
  if (folder) return <span className="file-icon" style={{ background: "#b58a1b" }} aria-hidden>DIR</span>;
  const ext = (name.split("?")[0].split(".").pop() ?? "").toLowerCase();
  const known = ext.length <= 4 && ext !== name.toLowerCase();
  return (
    <span className="file-icon" style={{ background: BY_EXT[ext] ?? "#6b7480" }} aria-hidden>
      {known ? ext.toUpperCase() : /^https?:/.test(name) ? "WEB" : "DOC"}
    </span>
  );
}
