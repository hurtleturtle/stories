import { useEffect, useState } from "react";

export type ThemePreference = "system" | "light" | "dark";

// Keep in sync with the inline script in index.html and the tokens in styles.css.
const STORAGE_KEY = "theme";
const THEME_COLORS = { light: "#f7f5fb", dark: "#16131c" };

function readPreference(): ThemePreference {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage can be unavailable (e.g. private mode); fall back to the OS setting.
  }
  return "system";
}

function applyPreference(pref: ThemePreference) {
  const root = document.documentElement;
  if (pref === "system") delete root.dataset.theme;
  else root.dataset.theme = pref;

  // Each theme-color meta is scoped to one OS scheme; an explicit choice overrides both.
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => {
    const scheme = meta.media.includes("dark") ? "dark" : "light";
    meta.content = THEME_COLORS[pref === "system" ? scheme : pref];
  });
}

/** Light/dark preference, persisted per browser. "system" follows the OS setting. */
export function useTheme() {
  const [pref, setPref] = useState<ThemePreference>(readPreference);

  useEffect(() => {
    applyPreference(pref);
    try {
      if (pref === "system") localStorage.removeItem(STORAGE_KEY);
      else localStorage.setItem(STORAGE_KEY, pref);
    } catch {
      // Not persisted; the choice still applies for this page load.
    }
  }, [pref]);

  return [pref, setPref] as const;
}
