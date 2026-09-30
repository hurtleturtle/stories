import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { LuDownload, LuPlus, LuTrash2 } from "react-icons/lu";
import { Link, useNavigate } from "react-router-dom";
import { apiErrorMessage } from "../api/client";
import { deleteTemplate, importBuiltinTemplates, listTemplates } from "../api/endpoints";
import type { Template } from "../api/types";

export default function Templates() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
  });

  function refresh() {
    setError(null);
    queryClient.invalidateQueries({ queryKey: ["templates"] });
  }

  const importMutation = useMutation({
    mutationFn: importBuiltinTemplates,
    onSuccess: refresh,
    onError: (err) => setError(apiErrorMessage(err, "Could not import the built-in templates.")),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: refresh,
    onError: (err) => setError(apiErrorMessage(err, "Could not delete the template.")),
  });

  function onDelete(t: Template) {
    if (window.confirm(`Delete the "${t.name}" template? Jobs that used it are kept.`)) {
      deleteMutation.mutate(t.id);
    }
  }

  return (
    <div>
      <h1>Templates</h1>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        {/* Short labels on phones so both buttons fit on one row. */}
        <button
          className="primary"
          type="button"
          aria-label="New template"
          onClick={() => navigate("/templates/new")}
        >
          <LuPlus />
          <span className="hide-sm">New template</span>
          <span className="show-sm">New</span>
        </button>
        <button
          className="secondary"
          onClick={() => importMutation.mutate()}
          disabled={importMutation.isPending}
          aria-label="Import built-in templates"
        >
          <LuDownload />
          <span className="hide-sm">Import built-in templates</span>
          <span className="show-sm">Import</span>
        </button>
      </div>

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {isLoading && <p>Loading...</p>}
      {templates && templates.length === 0 && <p>No templates yet.</p>}
      {templates && templates.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Name</th>
                <th>Container</th>
                <th>Ebook type</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {templates.map((t) => (
                <tr key={t.id}>
                  <td>
                    <Link to={`/templates/${t.id}`}>{t.name}</Link>
                  </td>
                  <td>{t.container}</td>
                  <td>{t.ebook_type}</td>
                  <td>
                    <button
                      className="secondary danger"
                      onClick={() => onDelete(t)}
                      disabled={deleteMutation.isPending}
                    >
                      <LuTrash2 />
                      Delete
                    </button>
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
