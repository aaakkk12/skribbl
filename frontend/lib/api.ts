const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000";

type ApiError = {
  detail?: string;
  [key: string]: unknown;
};

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    credentials: "include",
  });

  if (!response.ok) {
    let payload: ApiError = { detail: "Request failed" };
    try {
      payload = (await response.json()) as ApiError;
    } catch {
      // ignore parsing errors
    }
    const message = payload.detail || "Request failed";
    throw new Error(message);
  }

  return (await response.json()) as T;
}



