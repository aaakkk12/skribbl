const API_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS || "10000");
const API_RETRY_COUNT = Number(process.env.NEXT_PUBLIC_API_RETRY_COUNT || "1");
const RETRYABLE_METHODS = new Set(["GET", "HEAD"]);

function normalizeBaseUrl(url: string): string {
  return url.replace(/\/+$/, "");
}

export function resolveApiBaseUrl(): string {
  const configuredBase = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configuredBase) {
    return normalizeBaseUrl(configuredBase);
  }

  if (typeof window !== "undefined") {
    const { hostname, origin } = window.location;
    if (hostname === "localhost" || hostname === "127.0.0.1") {
      return "http://localhost:8000";
    }
    return origin;
  }

  return "http://localhost:8000";
}

export function resolveWsBaseUrl(): string {
  return resolveApiBaseUrl().replace(/^http/i, "ws");
}

type ApiError = {
  detail?: string;
  [key: string]: unknown;
};

function extractErrorMessage(payload: unknown): string | null {
  if (!payload) {
    return null;
  }
  if (typeof payload === "string") {
    return payload;
  }
  if (Array.isArray(payload)) {
    for (const item of payload) {
      const nested = extractErrorMessage(item);
      if (nested) return nested;
    }
    return null;
  }
  if (typeof payload === "object") {
    const typed = payload as Record<string, unknown>;
    if (typeof typed.detail === "string" && typed.detail.trim()) {
      return typed.detail;
    }
    for (const key of Object.keys(typed)) {
      const nested = extractErrorMessage(typed[key]);
      if (nested) {
        return nested;
      }
    }
  }
  return null;
}

let refreshPromise: Promise<boolean> | null = null;

async function refreshAccessToken(): Promise<boolean> {
  if (refreshPromise) {
    return refreshPromise;
  }
  refreshPromise = (async () => {
    try {
      const apiBase = resolveApiBaseUrl();
      const response = await fetch(`${apiBase}/api/auth/token/refresh/`, {
        method: "POST",
        credentials: "include",
        headers: {
          Accept: "application/json",
        },
      });
      return response.ok;
    } catch {
      return false;
    } finally {
      refreshPromise = null;
    }
  })();
  return refreshPromise;
}

export async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  attempt = 0,
  allowRefresh = true
): Promise<T> {
  const method = (options.method || "GET").toUpperCase();
  const hasBody = options.body !== undefined && options.body !== null;
  const headers = new Headers(options.headers || {});
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  // Avoid adding JSON Content-Type to GET/HEAD requests to prevent extra CORS preflight.
  if (hasBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), API_TIMEOUT_MS);

  let response: Response;
  try {
    const apiBase = resolveApiBaseUrl();
    response = await fetch(`${apiBase}${path}`, {
      ...options,
      method,
      headers,
      credentials: "include",
      signal: options.signal || controller.signal,
    });
  } catch (error) {
    const canRetry =
      RETRYABLE_METHODS.has(method) &&
      attempt < API_RETRY_COUNT &&
      !(options.signal && options.signal.aborted);
    if (canRetry) {
      const backoffMs = 150 * (attempt + 1);
      await new Promise((resolve) => setTimeout(resolve, backoffMs));
      return apiFetch<T>(path, options, attempt + 1, allowRefresh);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }

  if (!response.ok) {
    const isRefreshPath = path.startsWith("/api/auth/token/refresh/");
    const isAuthBootstrapPath = path.startsWith("/api/auth/guest-session/");
    if (
      response.status === 401 &&
      allowRefresh &&
      !isRefreshPath &&
      !isAuthBootstrapPath
    ) {
      const refreshed = await refreshAccessToken();
      if (refreshed) {
        return apiFetch<T>(path, options, attempt, false);
      }
    }

    let payload: ApiError = { detail: "Request failed" };
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      // ignore parsing errors
    }
    const message = extractErrorMessage(payload) || "Request failed";
    throw new Error(message);
  }

  if (response.status === 204) {
    return {} as T;
  }

  return (await response.json()) as T;
}

export type AvatarConfig = {
  color: string;
  eyes: "dot" | "happy" | "sleepy";
  mouth: "smile" | "flat" | "open";
  accessory: "none" | "cap" | "crown" | "glasses";
};

export type GuestCharacter =
  | "sprinter"
  | "captain"
  | "vision"
  | "joker"
  | "royal"
  | "ninja";

export type GuestSessionResponse = {
  device_id: string;
  character: GuestCharacter;
  user: {
    id: number;
    email: string;
    first_name: string;
    last_name: string;
    display_name: string;
    profile_completed: boolean;
    avatar: AvatarConfig;
  };
};

export async function createGuestSession(payload: {
  username: string;
  character: GuestCharacter;
  device_id?: string;
}) {
  return apiFetch<GuestSessionResponse>("/api/auth/guest-session/", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
