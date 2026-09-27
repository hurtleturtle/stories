import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { listJobs } from "../api/endpoints";
import type { JobStatus } from "../api/types";

const ACTIVE_STATUSES: JobStatus[] = ["pending", "running"];

export default function Jobs() {
  const navigate = useNavigate();
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
      <div className="row-between page-header">
        <h1>Jobs</h1>
        <button className="primary with-icon" type="button" onClick={() => navigate("/jobs/new")}>
          <svg
            width="16"
            height="16"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <path d="M8 3v10M3 8h10" />
          </svg>
          New job
        </button>
      </div>
      {isLoading && <p>Loading...</p>}
      {data && data.items.length === 0 && <p>No jobs yet. Start one with "New job".</p>}
      {data && data.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Title</th>
                <th>Status</th>
                <th className="hide-sm">Chapters</th>
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
                  <td className="hide-sm">{job.chapters_scraped}</td>
                  <td>
                    <span className="hide-sm">{new Date(job.created_at).toLocaleString()}</span>
                    <span className="show-sm">
                      {new Date(job.created_at).toLocaleDateString(undefined, {
                        day: "numeric",
                        month: "short",
                      })}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
