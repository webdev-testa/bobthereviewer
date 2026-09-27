import { useEffect, useState } from "react";

export type Theme = "light" | "dark";

const STORAGE_KEY = "bobreviewer-theme";

function initialTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark") return stored;
  } catch {
    // Storage can be unavailable (private mode, blocked site data); fall back to the system setting.
  }
  return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(initialTheme);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem(STORAGE_KEY, theme);
    } catch {
      // Not persisting is fine; the toggle still works for this visit.
    }
  }, [theme]);

  return { theme, toggle: () => setTheme((current) => (current === "light" ? "dark" : "light")) };
}
