import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { apiErrorMessage } from "../api/client";
import {
  artifactDownloadUrl,
  cancelJob,
  getJob,
  retryJob,
  sendJobToKindle,
} from "../api/endpoints";
import type { EmailStatus } from "../api/types";

const EMAIL_LABELS: Record<EmailStatus, string> = {
  not_sent: "Not sent",
  pending: "Sending",
  sent: "Sent",
  failed: "Failed",
};

// Reuses the job-status badge colours: muted / amber / green / red.
const EMAIL_BADGES: Record<EmailStatus, string> = {
  not_sent: "badge-cancelled",
  pending: "badge-pending",
  sent: "badge-success",
  failed: "badge-failed",
};

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: job, isLoading } = useQuery({
    queryKey: ["jobs", id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const data = query.state.data;
      if (!data) return false;
      const busy =
        data.status === "pending" ||
        data.status === "running" ||
        data.email_status === "pending";
      return busy ? 2000 : false;
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["jobs", id] });

  const retryMutation = useMutation({ mutationFn: () => retryJob(id!), onSuccess: invalidate });
  const cancelMutation = useMutation({ mutationFn: () => cancelJob(id!), onSuccess: invalidate });
  const emailMutation = useMutation({
    mutationFn: (artifactId?: string) => sendJobToKindle(id!, artifactId),
    onSuccess: (updated) => queryClient.setQueryData(["jobs", id], updated),
  });

  if (isLoading || !job) return <p>Loading...</p>;

  const completed = job.status === "success";
  // Only the in-flight request disables the button. A job stuck on "pending"
  // (worker down, task lost) must stay re-sendable rather than dead-ending.
  const queued = job.email_status === "pending";
  const sendLabel = job.email_status === "not_sent" ? "Send to Kindle" : "Resend to Kindle";

  return (
    <div>
      <h1>{job.title}</h1>
      <p>
        <span className={`badge badge-${job.status}`}>{job.status}</span>{" "}
        <a href={job.url} target="_blank" rel="noreferrer">
          {job.url}
        </a>
      </p>

      <div className="card">
        <strong>Chapters scraped:</strong> {job.chapters_scraped}
        {job.num_chapters ? ` / ${job.num_chapters}` : ""}
        <br />
        <strong>Created:</strong> {new Date(job.created_at).toLocaleString()}
        {job.finished_at && (
          <>
            <br />
            <strong>Finished:</strong> {new Date(job.finished_at).toLocaleString()}
          </>
        )}
      </div>

      {completed && (
        <div className="card">
          <div className="row-between">
            <div>
              <strong>Send to Kindle</strong>{" "}
              <span className={`badge ${EMAIL_BADGES[job.email_status]}`}>
                {EMAIL_LABELS[job.email_status]}
              </span>
              {job.email_recipient && (
                <>
                  <br />
                  <span className="muted">
                    {job.email_status === "sent" ? "Delivered to" : "Recipient"}{" "}
                    {job.email_recipient}
                    {job.email_sent_at &&
                      ` on ${new Date(job.email_sent_at).toLocaleString()}`}
                  </span>
                </>
              )}
            </div>
            <button
              className="primary"
              onClick={() => emailMutation.mutate(undefined)}
              disabled={emailMutation.isPending}
            >
              {emailMutation.isPending || queued ? "Sending..." : sendLabel}
            </button>
          </div>
          {job.email_error && <p className="error">{job.email_error}</p>}
          {emailMutation.isError && (
            <p className="error">
              {apiErrorMessage(emailMutation.error, "Could not send the email.")}
            </p>
          )}
        </div>
      )}

      {job.error && (
        <div className="card">
          <strong>Error</strong>
          <pre className="log">{job.error}</pre>
        </div>
      )}

      {job.log && (
        <div className="card">
          <strong>Log</strong>
          <pre className="log">{job.log}</pre>
        </div>
      )}

      {job.artifacts.length > 0 && (
        <div className="card">
          <strong>Artifacts</strong>
          <div className="table-wrap">
            <table>
              <tbody>
                {job.artifacts.map((artifact) => (
                  <tr key={artifact.id}>
                    <td>{artifact.filename}</td>
                    <td>{(artifact.size_bytes / 1024).toFixed(1)} KB</td>
                    <td>
                      <a href={artifactDownloadUrl(job.id, artifact.id)}>Download</a>
                    </td>
                    <td>
                      {completed && artifact.kind !== "html" && (
                        <button
                          className="secondary"
                          onClick={() => emailMutation.mutate(artifact.id)}
                          disabled={emailMutation.isPending}
                        >
                          Send this
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div style={{ display: "flex", gap: "0.5rem" }}>
        {job.status === "pending" && (
          <button className="secondary" onClick={() => cancelMutation.mutate()}>
            Cancel
          </button>
        )}
        {(job.status === "failed" || job.status === "cancelled") && (
          <button className="secondary" onClick={() => retryMutation.mutate()}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}
