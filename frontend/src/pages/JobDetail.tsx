import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import {
  artifactDownloadUrl,
  cancelJob,
  emailArtifact,
  getJob,
  retryJob,
} from "../api/endpoints";

export default function JobDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const { data: job, isLoading } = useQuery({
    queryKey: ["jobs", id],
    queryFn: () => getJob(id!),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "pending" || status === "running" ? 2000 : false;
    },
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["jobs", id] });

  const retryMutation = useMutation({ mutationFn: () => retryJob(id!), onSuccess: invalidate });
  const cancelMutation = useMutation({ mutationFn: () => cancelJob(id!), onSuccess: invalidate });
  const emailMutation = useMutation({
    mutationFn: (artifactId: string) => emailArtifact(id!, artifactId),
  });

  if (isLoading || !job) return <p>Loading...</p>;

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
                      <button
                        className="secondary"
                        onClick={() => emailMutation.mutate(artifact.id)}
                        disabled={emailMutation.isPending}
                      >
                        Email to Kindle
                      </button>
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
