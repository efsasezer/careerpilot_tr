import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiRequest } from "./client";
import { useAuth } from "./auth";
import type {
  CalendarData, EventInput, JobDetail, MatchResponse, NotificationList, NotificationSettings,
  Profile, ProfileUpdate, Source, SyncStatus, Task, TaskInput, Tracking, Verification,
} from "../../types/api";

interface QueryOptions {
  enabled?: boolean;
  refetchInterval?: number | false | ((query: { state: { data: unknown } }) => number | false);
}

export function useApiQuery<T>(key: string, path: string, options: QueryOptions = {}) {
  const { authenticated } = useAuth();
  return useQuery({
    queryKey: [key],
    queryFn: () => apiRequest<T>(path),
    enabled: authenticated && options.enabled !== false,
    staleTime: 30_000,
    refetchInterval: options.refetchInterval as never,
    retry: (count, error) => count < 1 && !(error instanceof ApiError && error.status === 401),
  });
}

function useApiMutation<TInput, TResult>(
  request: (input: TInput) => { path: string; method: string; body?: unknown },
  invalidate: string[],
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (input: TInput) => {
      const { path, method, body } = request(input);
      return apiRequest<TResult>(path, { method, body: body === undefined ? undefined : JSON.stringify(body) });
    },
    onSuccess: () => {
      void Promise.all(invalidate.map((key) => queryClient.invalidateQueries({ predicate: (query) => String(query.queryKey[0]).startsWith(key) })))
        .catch(() => undefined);
    },
  });
}

const JOB_KEYS = ["matches", "job:", "calendar", "notifications"];

export const useProfile = () => useApiQuery<Profile>("profile", "/profile");
export const useMatches = () => useApiQuery<MatchResponse>("matches", "/matches");
export const useSources = () => useApiQuery<Source[]>("sources", "/sources");
export const useJobDetail = (jobId: number | null) =>
  useApiQuery<JobDetail>(`job:${jobId}`, `/jobs/${jobId}/detail`, { enabled: jobId !== null });
export const useNotifications = () =>
  useApiQuery<NotificationList>("notifications", "/notifications?limit=100", { refetchInterval: 5 * 60_000 });
export const useNotificationSettings = () =>
  useApiQuery<NotificationSettings>("notification-settings", "/notifications/settings");
export const useSyncStatus = () =>
  useApiQuery<SyncStatus>("sync-status", "/sync/status", {
    refetchInterval: (query) => ((query.state.data as SyncStatus | undefined)?.running ? 2_500 : 60_000),
  });
export const useCalendar = (start: string, end: string) =>
  useApiQuery<CalendarData>(`calendar:${start}:${end}`, `/calendar?start=${start}&end=${end}`);
export const useTasks = () => useApiQuery<Task[]>("tasks", "/tasks");

export const useUpdateProfile = () =>
  useApiMutation<ProfileUpdate, Profile>((body) => ({ path: "/profile", method: "PUT", body }), ["profile", ...JOB_KEYS]);
export const useStartSync = () =>
  useApiMutation<void, SyncStatus>(() => ({ path: "/sync", method: "POST" }), ["sync-status"]);
export const useSetTracking = () =>
  useApiMutation<{ jobId: number; tracking: Tracking; notes?: string }, unknown>(
    ({ jobId, ...body }) => ({ path: `/jobs/${jobId}/tracking`, method: "PATCH", body }), JOB_KEYS,
  );
interface VerificationInput { jobId: number; decision: "eligible" | "not_eligible"; position_id?: string; note?: string }

export const useSetVerification = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, ...body }: VerificationInput) =>
      apiRequest(`/jobs/${jobId}/verification`, { method: "PUT", body: JSON.stringify(body) }),
    onMutate: async (input) => {
      await queryClient.cancelQueries({ queryKey: ["matches"] });
      const previous = queryClient.getQueryData<MatchResponse>(["matches"]);
      if (previous) {
        const category = input.decision === "eligible" ? "UYGUN" : "UYGUN DEĞİL";
        const verification: Verification = {
          decision: input.decision,
          scope: input.position_id ? "position" : "job",
          note: input.note ?? "",
          verified_at: new Date().toISOString(),
          stale: false,
          changes: [],
        };
        queryClient.setQueryData<MatchResponse>(["matches"], {
          ...previous,
          jobs: previous.jobs.map((position) => {
            if (position.parent_job_id !== input.jobId) return position;
            if (input.position_id && position.id !== input.position_id) return position;
            if (!input.position_id && position.verification?.scope === "position") return position;
            return { ...position, category, verification };
          }),
        });
      }
      return { previous };
    },
    onError: (_error, _input, context) => {
      if (context?.previous) queryClient.setQueryData(["matches"], context.previous);
    },
    onSettled: (_data, _error, input) => {
      const keys = ["matches", `job:${input.jobId}`, "calendar", "notifications", "sources"];
      void Promise.all(keys.map((key) => queryClient.invalidateQueries({
        predicate: (query) => String(query.queryKey[0]).startsWith(key),
      }))).catch(() => undefined);
    },
  });
};
export const useClearVerification = () =>
  useApiMutation<{ jobId: number; position_id?: string }, unknown>(
    ({ jobId, position_id }) => ({ path: `/jobs/${jobId}/verification?position_id=${encodeURIComponent(position_id ?? "")}`, method: "DELETE" }), JOB_KEYS,
  );
export const useAcknowledgeUpdate = () =>
  useApiMutation<number, unknown>((jobId) => ({ path: `/jobs/${jobId}/verification/acknowledge`, method: "POST" }), JOB_KEYS);
export const useRetryReading = () =>
  useApiMutation<number, { status: string; error?: string; ocr_confidence?: number | null }>(
    (jobId) => ({ path: `/jobs/${jobId}/ocr`, method: "POST" }), ["sources", ...JOB_KEYS],
  );
export const useAddEvent = () =>
  useApiMutation<{ jobId: number } & EventInput, unknown>(({ jobId, ...body }) => ({ path: `/jobs/${jobId}/events`, method: "POST", body }), JOB_KEYS);
export const useEditEvent = () =>
  useApiMutation<{ id: number } & EventInput, unknown>(({ id, ...body }) => ({ path: `/events/${id}`, method: "PATCH", body }), JOB_KEYS);
export const useDeleteEvent = () =>
  useApiMutation<number, unknown>((id) => ({ path: `/events/${id}`, method: "DELETE" }), JOB_KEYS);
export const useVerifyEvent = () =>
  useApiMutation<number, unknown>((id) => ({ path: `/events/${id}/verify`, method: "POST" }), JOB_KEYS);
export const useSaveTask = () =>
  useApiMutation<TaskInput & { id?: number }, Task>(
    ({ id, ...body }) => ({ path: id ? `/tasks/${id}` : "/tasks", method: id ? "PATCH" : "POST", body }), ["tasks", "calendar", "notifications"],
  );
export const useCompleteTask = () =>
  useApiMutation<{ id: number; day: string; done: boolean }, Task>(
    ({ id, ...body }) => ({ path: `/tasks/${id}/complete`, method: "POST", body }), ["tasks", "calendar", "notifications"],
  );
export const useDeleteTask = () =>
  useApiMutation<number, unknown>((id) => ({ path: `/tasks/${id}`, method: "DELETE" }), ["tasks", "calendar", "notifications"]);
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
