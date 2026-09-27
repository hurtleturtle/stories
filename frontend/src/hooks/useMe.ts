import { useQuery } from "@tanstack/react-query";
import { getMe } from "../api/endpoints";

/** The logged-in user. Cached for the session; logging out clears it. */
export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: getMe, staleTime: Infinity });
}
