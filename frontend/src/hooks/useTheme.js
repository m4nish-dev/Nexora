import { useCallback, useState } from "react";

const STORAGE_KEY = "nexora-theme";

export function useTheme() {
  const [theme, setThemeState] = useState(() => document.documentElement.dataset.theme || "light");

  const setTheme = useCallback((next) => {
    document.documentElement.dataset.theme = next;
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* storage unavailable (private mode) — theme still applies for this visit */
    }
    setThemeState(next);
  }, []);

  return { theme, setTheme };
}
