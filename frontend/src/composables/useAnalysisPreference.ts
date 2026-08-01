const STORAGE_KEY = "analysis_mode_preference";

export type AnalysisMode = "cache" | "fresh";

export function useAnalysisPreference() {
  function getPreference(): AnalysisMode | null {
    try {
      const val = localStorage.getItem(STORAGE_KEY);
      if (val === "cache" || val === "fresh") return val;
      return null;
    } catch {
      return null;
    }
  }

  function setPreference(mode: AnalysisMode): void {
    try {
      localStorage.setItem(STORAGE_KEY, mode);
    } catch {
      // incognito or storage full — silently ignore
    }
  }

  return { getPreference, setPreference };
}
