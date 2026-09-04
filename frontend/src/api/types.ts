export type JobStatus = "pending" | "running" | "success" | "failed" | "cancelled";

export interface Template {
  id: string;
  name: string;
  site_hostname: string | null;
  container: string;
  next_selector: string;
  detect_title: string | null;
  style: string;
  scripts: string[];
  ebook_type: string;
  extra: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface TemplateInput {
  name: string;
  site_hostname?: string | null;
  container: string;
  next_selector: string;
  detect_title?: string | null;
  style?: string;
  scripts?: string[];
  ebook_type?: string;
}

export interface Artifact {
  id: string;
  kind: string;
  filename: string;
  size_bytes: number;
  content_type: string;
}

export interface Job {
  id: string;
  url: string;
  title: string;
  status: JobStatus;
  config: Record<string, unknown>;
  num_chapters: number | null;
  chapters_scraped: number;
  error: string | null;
  log: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  artifacts: Artifact[];
}

export interface JobList {
  items: Job[];
  total: number;
}

export interface JobCreateInput {
  url: string;
  template_id?: string | null;
  title?: string;
  container?: string;
  next_selector?: string;
  detect_title?: string;
  style?: string;
  scripts?: string[];
  ebook_type?: string;
  num_chapters?: number;
  send_email?: boolean;
}

export interface UserSettings {
  kindle_address: string | null;
  email_from: string | null;
  smtp_host: string;
  smtp_port: number;
  smtp_username: string | null;
  smtp_password_set: boolean;
  auto_send_default: boolean;
}
