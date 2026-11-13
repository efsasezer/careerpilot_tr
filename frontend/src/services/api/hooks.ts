import { useQuery } from "@tanstack/react-query";
import { apiRequest } from "./client";
import { useAuth } from "./auth";
import type {
  Health,
  Job,
  MatchResponse,
  Profile,
  SkillAnalytics,
  Source,
} from "../../types/api";

export function useApiQuery<T>(key: string, path: string) {
  const { token } = useAuth();
  return useQuery({
    queryKey: [key, token],
    queryFn: () => apiRequest<T>(path, token ?? ""),
    enabled: Boolean(token),
    staleTime: 30_000,
    retry: (count, error) =>
      count < 1 && !(error instanceof Error && "status" in error && error.status === 401),
  });
}

export const useHealth = () => useApiQuery<Health>("health", "/health");
export const useProfile = () => useApiQuery<Profile>("profile", "/profile");
export const useMatches = () =>
  useApiQuery<MatchResponse>("matches", "/public/matches");
export const useSources = () => useApiQuery<Source[]>("sources", "/sources");
export const useJobs = () => useApiQuery<Job[]>("jobs", "/jobs");
export const useSkillAnalytics = (category: string) =>
  useApiQuery<SkillAnalytics>(
    `skills:${category}`,
    `/analytics/skills${category ? `?category=${encodeURIComponent(category)}` : ""}`,
  );
