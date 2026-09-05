import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { deleteTemplate, importBuiltinTemplates, listTemplates } from "../api/endpoints";

export default function Templates() {
  const queryClient = useQueryClient();
  const { data: templates, isLoading } = useQuery({
    queryKey: ["templates"],
    queryFn: listTemplates,
  });

  const importMutation = useMutation({
    mutationFn: importBuiltinTemplates,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteTemplate,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["templates"] }),
  });

  return (
    <div>
      <h1>Templates</h1>
      <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
        <Link to="/templates/new">
          <button className="primary" type="button">
            New template
          </button>
        </Link>
        <button
          className="secondary"
          onClick={() => importMutation.mutate()}
          disabled={importMutation.isPending}
        >
          Import built-in templates
        </button>
      </div>

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
                    <button className="secondary" onClick={() => deleteMutation.mutate(t.id)}>
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
