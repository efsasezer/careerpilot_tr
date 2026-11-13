const API_URL = (import.meta.env.VITE_API_URL || "http://127.0.0.1:8000").replace(
  /\/+$/,
  "",
);

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiRequest<T>(
  path: string,
  token: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_URL}${path}`, { ...init, headers });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as
      | { detail?: string }
      | null;
    throw new ApiError(
      body?.detail || `API isteği başarısız (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export function getApiUrl() {
  return API_URL;
}
