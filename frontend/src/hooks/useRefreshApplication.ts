import { useQueryClient } from "@tanstack/react-query";

const REFRESH = ["application", "history", "pipeline", "interview", "match", "attempt-by-app", "applications-mine"];

/** Refreshes everything that shows an application's progress (journey, status, attempts, interviews, match). */
export function useRefreshApplication() {
  const qc = useQueryClient();
  return () => REFRESH.forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
}
