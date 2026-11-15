import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "./client";
import { useAuth } from "./auth";
import type {
  Health, JobDetail, MatchResponse, NotificationList, NotificationSettings,
  Profile, ProfileUpdate, Source, SyncStatus, Tracking,
} from "../../types/api";

interface QueryOptions {
  enabled?: boolean;
  refetchInterval?: number | false | ((query: { state: { data: unknown } }) => number | false);
}

export function useApiQuery<T>(key: string, path: string, options: QueryOptions = {}) {
  const { token } = useAuth();
  return useQuery({
    queryKey: [key, token],
    queryFn: () => apiRequest<T>(path, token ?? ""),
    enabled: Boolean(token) && options.enabled !== false,
    staleTime: 30_000,
    refetchInterval: options.refetchInterval as never,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status === 401),
  });
}

function useApiMutation<TInput, TResult>(
  request: (input: TInput) => { path: string; method: string; body?: unknown },
  invalidate: string[],
) {
  const { token } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TInput) => {
      const { path, method, body } = request(input);
      return apiRequest<TResult>(path, token ?? "", { method, body: body === undefined ? undefined : JSON.stringify(body) });
    },
    onSuccess: () => Promise.all(invalidate.map((key) => queryClient.invalidateQueries({ queryKey: [key] }))),
  });
}

export const useHealth = () => useApiQuery<Health>("health", "/health");
export const useProfile = () => useApiQuery<Profile>("profile", "/profile");
export const useMatches = () => useApiQuery<MatchResponse>("matches", "/matches");
export const useSources = () => useApiQuery<Source[]>("sources", "/sources");
export const useJobDetail = (jobId: number | null) =>
  useApiQuery<JobDetail>(`job:${jobId}`, `/jobs/${jobId}/detail`, { enabled: jobId !== null });
export const useNotifications = () =>
  useApiQuery<NotificationList>("notifications", "/notifications?limit=100", { refetchInterval: 60_000 });
export const useNotificationSettings = () =>
  useApiQuery<NotificationSettings>("notification-settings", "/notifications/settings");
export const useSyncStatus = () =>
  useApiQuery<SyncStatus>("sync-status", "/sync/status", {
    refetchInterval: (query) => ((query.state.data as SyncStatus | undefined)?.running ? 2_500 : 60_000),
  });

export const useUpdateProfile = () =>
  useApiMutation<ProfileUpdate, Profile>((body) => ({ path: "/profile", method: "PUT", body }), ["profile", "matches", "notifications"]);
export const useStartSync = () =>
  useApiMutation<void, SyncStatus>(() => ({ path: "/sync", method: "POST" }), ["sync-status"]);
export const useSetTracking = () =>
  useApiMutation<{ jobId: number; tracking: Tracking; notes?: string }, unknown>(
    ({ jobId, ...body }) => ({ path: `/jobs/${jobId}/tracking`, method: "PATCH", body }),
    ["matches", "notifications"],
  );
export const useReadNotification = () =>
  useApiMutation<number, unknown>((id) => ({ path: `/notifications/${id}/read`, method: "POST" }), ["notifications"]);
export const useReadAllNotifications = () =>
  useApiMutation<void, unknown>(() => ({ path: "/notifications/read-all", method: "POST" }), ["notifications"]);
export const useSaveNotificationSettings = () =>
  useApiMutation<NotificationSettings, NotificationSettings>(
    (body) => ({ path: "/notifications/settings", method: "PUT", body }), ["notification-settings", "notifications"],
  );
export const useTestNotification = () =>
  useApiMutation<void, { channels: Record<string, string> }>(() => ({ path: "/notifications/test", method: "POST" }), []);
