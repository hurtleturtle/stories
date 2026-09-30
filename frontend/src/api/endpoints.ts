import { api } from "./client";
import type {
  AdminUser,
  AdminUserList,
  AdminUserUpdate,
  AppSettings,
  Artifact,
  Job,
  JobCreateInput,
  JobList,
  Template,
  TemplateInput,
  User,
  Options,
  UserSettings,
  UserSettingsInput,
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

export async function getMe(): Promise<User> {
  const { data } = await api.get("/auth/me");
  return data;
}

/** Whether new accounts can currently be created. Needs no login. */
export async function getRegistrationOpen(): Promise<boolean> {
  const { data } = await api.get("/auth/registration");
  return data.open;
}

export async function listUsers(q?: string): Promise<AdminUserList> {
  const { data } = await api.get("/admin/users", { params: { limit: 200, ...(q ? { q } : {}) } });
  return data;
}

export async function updateUser(id: string, input: AdminUserUpdate): Promise<AdminUser> {
  const { data } = await api.patch(`/admin/users/${id}`, input);
  return data;
}

export async function deleteUser(id: string): Promise<void> {
  await api.delete(`/admin/users/${id}`);
}

export async function getAppSettings(): Promise<AppSettings> {
  const { data } = await api.get("/admin/settings");
  return data;
}

export async function updateAppSettings(input: AppSettings): Promise<AppSettings> {
  const { data } = await api.put("/admin/settings", input);
  return data;
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

export async function getOptions(): Promise<Options> {
  const { data } = await api.get("/options");
  return data;
}

export async function getSettings(): Promise<UserSettings> {
  const { data } = await api.get("/settings");
  return data;
}

export async function updateSettings(input: UserSettingsInput): Promise<UserSettings> {
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

/** Download an artifact and save it under its own filename.
 *
 * Fetched through the API client rather than a plain link: the endpoint needs
 * the bearer token, which a browser navigation would not send. */
export async function downloadArtifact(jobId: string, artifact: Artifact): Promise<void> {
  const { data } = await api.get<Blob>(`/jobs/${jobId}/artifacts/${artifact.id}`, {
    responseType: "blob",
  });
  const url = URL.createObjectURL(data);
  const link = document.createElement("a");
  link.href = url;
  link.download = artifact.filename;
  link.click();
  // Give the browser a moment to start the save before the blob is released.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** (Re)send a completed job to Kindle. Omit the artifact to send the job's ebook. */
export async function sendJobToKindle(jobId: string, artifactId?: string): Promise<Job> {
  const { data } = await api.post(`/jobs/${jobId}/email`, {
    artifact_id: artifactId ?? null,
  });
  return data;
}
