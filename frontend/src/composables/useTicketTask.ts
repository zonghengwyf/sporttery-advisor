const STORAGE_KEY = "active_ticket_task";

export interface TicketTaskState {
  taskId: string;
  matchIds: number[];
}

export function useTicketTask() {
  function save(taskId: string, matchIds: number[]): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify({ taskId, matchIds }));
    } catch {
      // incognito or storage full
    }
  }

  function clear(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
  }

  function getSaved(): TicketTaskState | null {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (
        typeof parsed?.taskId === "string" &&
        Array.isArray(parsed?.matchIds)
      ) {
        return parsed as TicketTaskState;
      }
      return null;
    } catch {
      return null;
    }
  }

  return { save, clear, getSaved };
}
