// API, arayüzle aynı alan adından /api altında sunulur (yerelde Vite vekili, yayında Render yönlendirmesi).
// Böylece oturum çerezi birinci taraf kalır; tarayıcıda şifre ya da anahtar saklanmaz.
const API_URL = (import.meta.env.VITE_API_URL || "/api").replace(/\/+$/, "");

export class ApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`${API_URL}${path}`, { ...init, headers, credentials: "include" });
  } catch {
    throw new ApiError("Sunucuya ulaşılamadı. Bağlantınızı kontrol edip tekrar deneyin.", 0);
  }
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const detail = typeof body?.detail === "string" ? body.detail : null;
    if (response.status === 401 && !path.startsWith("/auth/")) window.dispatchEvent(new Event("careerpilot:unauthorized"));
    throw new ApiError(
      detail || (init.method && init.method !== "GET" ? "Kaydedilemedi, tekrar dene." : `İstek başarısız (${response.status})`),
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export function getApiUrl() {
  return API_URL;
}
