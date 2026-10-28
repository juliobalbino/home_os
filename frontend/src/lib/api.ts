const API = import.meta.env.VITE_API_BASE_URL ?? "/api/v1";

export function apiOriginFromBase(apiBase: string, pageOrigin: string): string {
  return new URL(apiBase, pageOrigin).origin;
}

export function apiOrigin(): string {
  return apiOriginFromBase(API, window.location.origin);
}

export function apiUrl(path: string): string {
  return `${API.replace(/\/$/, "")}/${path.replace(/^\//, "")}`;
}

export type User = { id: number; email: string; name: string };
export type Role = "owner" | "member" | "viewer" | string;
export type Household = {
  id: string;
  name: string;
  role: Role;
  timezone?: string;
};
export type Member = { id: number; name: string; role: Role };
export type Balance = {
  membership_id: number;
  name: string;
  balance_minor: number;
};
export type Summary = { spent_total: number; budget_total: number };
export type Occurrence = {
  id: number;
  title: string;
  due_at: string;
  status: string;
  assigned_name?: string | null;
};

function errorMessage(data: unknown, fallback: string): string {
  if (data && typeof data === "object") {
    const record = data as Record<string, unknown>;
    if (typeof record.detail === "string") return record.detail;
    const details = Object.values(record).flat().join(" ").trim();
    if (details) return details;
  }
  return fallback;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(apiUrl(path), {
    credentials: "include",
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
  });
  const data = await response.json();
  if (!response.ok)
    throw new Error(errorMessage(data, "Falha na solicitação."));
  return data as T;
}

/** Sends an unsafe request with a fresh CSRF token. */
export async function send<T = unknown>(
  path: string,
  payload: unknown,
  method = "POST",
  headers: Record<string, string> = {},
): Promise<T> {
  const csrf = await request<{ csrfToken: string }>("/auth/csrf");
  return request<T>(path, {
    method,
    headers: { "X-CSRFToken": csrf?.csrfToken, ...headers },
    body: typeof payload === "string" ? payload : JSON.stringify(payload),
  });
}

export function reason(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

/** API responses are trusted for shape only after this guard. */
export function list<T>(value: unknown): T[] {
  return Array.isArray(value) ? (value as T[]) : [];
}

export const roleLabel = (role: Role) =>
  role === "owner"
    ? "Responsável"
    : role === "viewer"
      ? "Visualização"
      : "Membro";
