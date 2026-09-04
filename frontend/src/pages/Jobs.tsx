import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listJobs } from "../api/endpoints";
import type { JobStatus } from "../api/types";

const ACTIVE_STATUSES: JobStatus[] = ["pending", "running"];

export default function Jobs() {
  const { data, isLoading } = useQuery({
    queryKey: ["jobs"],
    queryFn: () => listJobs(),
    refetchInterval: (query) => {
      const jobs = query.state.data?.items ?? [];
      return jobs.some((j) => ACTIVE_STATUSES.includes(j.status)) ? 3000 : false;
    },
  });

  return (
    <div>
      <h1>Jobs</h1>
      {isLoading && <p>Loading...</p>}
      {data && data.items.length === 0 && <p>No jobs yet. Start one from "New job".</p>}
      {data && data.items.length > 0 && (
        <table>
          <thead>
            <tr>
              <th>Title</th>
              <th>Status</th>
              <th>Chapters</th>
              <th>Created</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((job) => (
              <tr key={job.id}>
                <td>
                  <Link to={`/jobs/${job.id}`}>{job.title}</Link>
                </td>
                <td>
                  <span className={`badge badge-${job.status}`}>{job.status}</span>
                </td>
                <td>{job.chapters_scraped}</td>
                <td>{new Date(job.created_at).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
