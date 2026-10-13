/** Light / Dark / Auto (follow the system), per browser. index.html applies the choice before the
 *  first paint; this sets html[data-theme], read by the palettes in styles.css. */
import { useState } from "react";

type Theme = "light" | "dark" | "system";
const KEY = "docling-studio.theme";
const NEXT: Record<Theme, Theme> = { system: "light", light: "dark", dark: "system" };
const LABEL: Record<Theme, string> = { system: "Auto", light: "Light", dark: "Dark" };

function read(): Theme {
  try {
    const v = localStorage.getItem(KEY);
    if (v === "light" || v === "dark") return v;
  } catch {
    /* default */
  }
  return "system";
}

export function ThemeToggle() {
  const [theme, setTheme] = useState<Theme>(read);
  const change = () => {
    const next = NEXT[theme];
    setTheme(next);
    if (next === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = next;
    try {
      if (next === "system") localStorage.removeItem(KEY);
      else localStorage.setItem(KEY, next);
    } catch {
      /* this browser only */
    }
  };
  return (
    <button className="ghost small" onClick={change} title={`Appearance: ${LABEL[theme]} (click to change)`} aria-label={`Appearance: ${LABEL[theme]}`}>
      {theme === "dark" ? "☾" : theme === "light" ? "☀" : "◐"} {LABEL[theme]}
    </button>
  );
}
