/** Advanced mode (Settings): shows the full Docling Studio pages alongside the everyday app. Per
 *  browser; whether the plan includes it is checked by the server's entitlements. */
import { useEffect, useState } from "react";
import { BRAND } from "../brand";

const KEY = BRAND.storagePrefix + "advanced";
const EVENT = "app:advanced";

export function isAdvanced(): boolean {
  try {
    return localStorage.getItem(KEY) === "1";
  } catch {
    return false;
  }
}

export function setAdvanced(on: boolean) {
  try {
    if (on) localStorage.setItem(KEY, "1");
    else localStorage.removeItem(KEY);
  } catch {
    /* this page only */
  }
  window.dispatchEvent(new Event(EVENT));
}

export function useAdvanced(): boolean {
  const [on, setOn] = useState(isAdvanced);
  useEffect(() => {
    const update = () => setOn(isAdvanced());
    window.addEventListener(EVENT, update);
    return () => window.removeEventListener(EVENT, update);
  }, []);
  return on;
}
