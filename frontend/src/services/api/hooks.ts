import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { apiRequest } from "./client";
import { useAuth } from "./auth";
import type {
  Health,
  Job,
  MatchResponse,
  Profile,
  ProfileUpdate,
  SkillAnalytics,
  Source,
  SourceSyncReport,
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
export function useUpdateProfile() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (profile: ProfileUpdate) => apiRequest<Profile>(
      "/profile",
      token ?? "",
      { method: "PUT", body: JSON.stringify(profile) },
    ),
    onSuccess: async (profile) => {
      queryClient.setQueryData(["profile", token], profile);
      await queryClient.invalidateQueries({ queryKey: ["matches", token] });
    },
  });
}
export const useMatches = () =>
  useApiQuery<MatchResponse>("matches", "/public/matches");
export const useSources = () => useApiQuery<Source[]>("sources", "/sources");
export function useSyncSources() {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => apiRequest<SourceSyncReport>(
      "/sources/sync-all",
      token ?? "",
      { method: "POST" },
    ),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["sources", token] }),
        queryClient.invalidateQueries({ queryKey: ["matches", token] }),
        queryClient.invalidateQueries({ queryKey: ["jobs", token] }),
      ]);
    },
  });
}
export const useJobs = () => useApiQuery<Job[]>("jobs", "/jobs");
export const useSkillAnalytics = (category: string) =>
  useApiQuery<SkillAnalytics>(
    `skills:${category}`,
    `/analytics/skills${category ? `?category=${encodeURIComponent(category)}` : ""}`,
  );
