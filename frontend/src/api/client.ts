import axios, { AxiosError } from "axios";

export const TOKEN_KEY = "story_scraper_token";

export const api = axios.create({ baseURL: "/api" });

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(TOKEN_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem(TOKEN_KEY);
      if (!location.pathname.startsWith("/login")) {
        location.href = "/login";
      }
    }
    return Promise.reject(error);
  },
);

export function setToken(token: string) {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem(TOKEN_KEY);
}

type ValidationIssue = { loc?: unknown; msg?: unknown };

/** One of FastAPI's validation errors as "field: message", e.g. "style: Unknown style ...". */
function describeIssue(issue: unknown): string {
  const { loc, msg } = (issue ?? {}) as ValidationIssue;
  if (typeof msg !== "string") return "";
  const text = msg.replace(/^Value error, /, "");
  const field = Array.isArray(loc)
    ? loc
        .filter((part) => part !== "body")
        .join(".")
        .replace(/_/g, " ")
    : "";
  return field ? `${field}: ${text}` : text;
}

/**
 * The API's explanation for a failed request, or a caller-supplied fallback.
 * `detail` is a string for errors the API raises itself, and a list of
 * validation issues when a request body is rejected.
 */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as AxiosError<{ detail?: unknown }>)?.response?.data?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    const messages = detail.map(describeIssue).filter(Boolean);
    if (messages.length > 0) return messages.join("; ");
  }
  return fallback;
}
