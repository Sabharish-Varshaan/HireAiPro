import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

export function useInstitution() {
  const mine = useQuery({ queryKey: ["my-institutions"], queryFn: () => api.get("/institutions/mine").then((r) => r.data) });
  return { inst: mine.data?.[0], isLoading: mine.isLoading, error: mine.error };
}
