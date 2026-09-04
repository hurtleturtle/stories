import { api } from "./client";
import type {
  Job,
  JobCreateInput,
  JobList,
  Template,
  TemplateInput,
  UserSettings,
} from "./types";

export async function login(email: string, password: string): Promise<string> {
  const form = new URLSearchParams();
  form.set("username", email);
  form.set("password", password);
  const { data } = await api.post("/auth/login", form, {
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
  });
  return data.access_token;
}

export async function register(email: string, password: string): Promise<void> {
  await api.post("/auth/register", { email, password });
}

export async function listTemplates(): Promise<Template[]> {
  const { data } = await api.get("/templates");
  return data;
}

export async function createTemplate(input: TemplateInput): Promise<Template> {
  const { data } = await api.post("/templates", input);
  return data;
}

export async function updateTemplate(
  id: string,
  input: Partial<TemplateInput>,
): Promise<Template> {
  const { data } = await api.put(`/templates/${id}`, input);
  return data;
}

export async function deleteTemplate(id: string): Promise<void> {
  await api.delete(`/templates/${id}`);
}

export async function importBuiltinTemplates(): Promise<Template[]> {
  const { data } = await api.post("/templates/import");
  return data;
}

export async function getSettings(): Promise<UserSettings> {
  const { data } = await api.get("/settings");
  return data;
}

export async function updateSettings(input: {
  kindle_address?: string;
  email_from?: string;
  smtp_host: string;
  smtp_port: number;
  smtp_username?: string;
  smtp_password?: string;
  auto_send_default: boolean;
}): Promise<UserSettings> {
  const { data } = await api.put("/settings", input);
  return data;
}

export async function listJobs(status?: string): Promise<JobList> {
  const { data } = await api.get("/jobs", { params: status ? { status } : {} });
  return data;
}

export async function getJob(id: string): Promise<Job> {
  const { data } = await api.get(`/jobs/${id}`);
  return data;
}

export async function createJob(input: JobCreateInput): Promise<Job> {
  const { data } = await api.post("/jobs", input);
  return data;
}

export async function retryJob(id: string): Promise<Job> {
  const { data } = await api.post(`/jobs/${id}/retry`);
  return data;
}

export async function cancelJob(id: string): Promise<Job> {
  const { data } = await api.post(`/jobs/${id}/cancel`);
  return data;
}

export async function deleteJob(id: string): Promise<void> {
  await api.delete(`/jobs/${id}`);
}

export function artifactDownloadUrl(jobId: string, artifactId: string): string {
  return `/api/jobs/${jobId}/artifacts/${artifactId}`;
}

export async function emailArtifact(jobId: string, artifactId: string): Promise<void> {
  await api.post(`/jobs/${jobId}/email`, null, { params: { artifact_id: artifactId } });
}
