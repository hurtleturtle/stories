import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { createJob, listTemplates } from "../api/endpoints";

export default function NewJob() {
  const [url, setUrl] = useState("");
  const [templateId, setTemplateId] = useState("");
  const [title, setTitle] = useState("");
  const [numChapters, setNumChapters] = useState("");
  const [sendEmail, setSendEmail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: listTemplates });

  const mutation = useMutation({
    mutationFn: createJob,
    onSuccess: (job) => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      navigate(`/jobs/${job.id}`);
    },
    onError: () => setError("Could not start job. Check the URL and try again."),
  });

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    mutation.mutate({
      url,
      template_id: templateId || null,
      title: title || undefined,
      num_chapters: numChapters ? Number(numChapters) : undefined,
      send_email: sendEmail,
    });
  }

  return (
    <div>
      <h1>New job</h1>
      <form onSubmit={onSubmit}>
        <label>
          Chapter URL
          <input
            type="url"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder="https://example.com/chapter-1"
            required
          />
        </label>
        <label>
          Template
          <select value={templateId} onChange={(e) => setTemplateId(e.target.value)}>
            <option value="">None (use defaults)</option>
            {templates?.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          Title (optional)
          <input value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>
        <label>
          Stop after N chapters (optional)
          <input
            type="number"
            min={1}
            value={numChapters}
            onChange={(e) => setNumChapters(e.target.value)}
          />
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={sendEmail}
            onChange={(e) => setSendEmail(e.target.checked)}
          />
          Email to Kindle when done
        </label>
        {error && <span className="error">{error}</span>}
        <button className="primary" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Starting..." : "Start job"}
        </button>
      </form>
    </div>
  );
}
