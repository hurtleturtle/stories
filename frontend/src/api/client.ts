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

/** The API's `detail` message for a failed request, or a caller-supplied fallback. */
export function apiErrorMessage(error: unknown, fallback: string): string {
  const detail = (error as AxiosError<{ detail?: string }>)?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}
