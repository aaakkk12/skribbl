const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";
const API_TIMEOUT_MS = Number(process.env.NEXT_PUBLIC_API_TIMEOUT_MS || "10000");
const API_RETRY_COUNT = Number(process.env.NEXT_PUBLIC_API_RETRY_COUNT || "1");
const RETRYABLE_METHODS = new Set(["GET", "HEAD"]);

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
      const response = await fetch(`${API_BASE}/api/auth/token/refresh/`, {
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
    response = await fetch(`${API_BASE}${path}`, {
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
    const isAuthPath =
      path.startsWith("/api/auth/login/") || path.startsWith("/api/auth/register/");
    if (
      response.status === 401 &&
      allowRefresh &&
      !isRefreshPath &&
      !isAuthPath
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

export type FriendUser = {
  id: number;
  email: string;
  name: string;
  avatar: AvatarConfig;
  friend_since?: string;
  is_friend?: boolean;
};

export type RoomInviteUser = {
  id: number;
  name: string;
  avatar: AvatarConfig;
};

export type IncomingInvite = {
  id: number;
  room_code: string;
  created_at: string;
  from_user: RoomInviteUser;
};

export type OutgoingInvite = {
  id: number;
  room_code: string;
  created_at: string;
  to_user: RoomInviteUser;
};

export async function searchUsers(query: string) {
  const encoded = encodeURIComponent(query.trim());
  return apiFetch<{ results: FriendUser[] }>(`/api/auth/users/search/?q=${encoded}`, {
    method: "GET",
  });
}

export async function getFriends() {
  return apiFetch<{ friends: FriendUser[] }>("/api/auth/friends/", {
    method: "GET",
  });
}

export async function addFriend(userId: number) {
  return apiFetch<{ detail: string; friend?: FriendUser }>("/api/auth/friends/", {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function unfriend(userId: number) {
  return apiFetch<{ detail: string }>(`/api/auth/friends/${userId}/`, {
    method: "DELETE",
  });
}

export async function sendRoomInvite(code: string, userId: number) {
  return apiFetch<{ detail: string }>(`/api/rooms/${code.toUpperCase()}/invite/`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });
}

export async function listRoomInvites() {
  return apiFetch<{ received: IncomingInvite[]; sent: OutgoingInvite[] }>(
    "/api/rooms/invites/",
    {
      method: "GET",
    }
  );
}

export async function respondRoomInvite(inviteId: number, action: "accept" | "reject") {
  return apiFetch<{ detail: string; code?: string }>(
    `/api/rooms/invites/${inviteId}/respond/`,
    {
      method: "POST",
      body: JSON.stringify({ action }),
    }
  );
}



