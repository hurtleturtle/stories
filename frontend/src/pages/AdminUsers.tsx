import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { apiErrorMessage } from "../api/client";
import {
  deleteUser,
  getAppSettings,
  listUsers,
  updateAppSettings,
  updateUser,
} from "../api/endpoints";
import type { AdminUser, AdminUserUpdate } from "../api/types";
import { useMe } from "../hooks/useMe";

export default function AdminUsers() {
  const queryClient = useQueryClient();
  const { data: me } = useMe();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: users, isLoading } = useQuery({
    queryKey: ["admin-users", search],
    queryFn: () => listUsers(search.trim() || undefined),
  });
  const { data: appSettings } = useQuery({
    queryKey: ["app-settings"],
    queryFn: getAppSettings,
  });

  function refresh() {
    setError(null);
    queryClient.invalidateQueries({ queryKey: ["admin-users"] });
    // Editing yourself (role, email) changes what the rest of the app shows.
    queryClient.invalidateQueries({ queryKey: ["me"] });
  }

  const settingsMutation = useMutation({
    mutationFn: updateAppSettings,
    // Flip the checkbox straight away rather than after the round trip.
    onMutate: (input) => {
      const previous = queryClient.getQueryData(["app-settings"]);
      queryClient.setQueryData(["app-settings"], input);
      return { previous };
    },
    onSuccess: (data) => queryClient.setQueryData(["app-settings"], data),
    onError: (err, _input, context) => {
      queryClient.setQueryData(["app-settings"], context?.previous);
      setError(apiErrorMessage(err, "Could not save the setting."));
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, input }: { id: string; input: AdminUserUpdate }) => updateUser(id, input),
    onSuccess: () => {
      setEditing(null);
      refresh();
    },
    onError: (err) => setError(apiErrorMessage(err, "Could not update the user.")),
  });

  const deleteMutation = useMutation({
    mutationFn: deleteUser,
    onSuccess: refresh,
    onError: (err) => setError(apiErrorMessage(err, "Could not delete the user.")),
  });

  // The API refuses to leave the instance without an active admin; this just
  // greys out the controls that would hit that.
  const activeAdmins = users?.items.filter((u) => u.role === "admin" && u.is_active).length ?? 0;
  function isLastAdmin(u: AdminUser) {
    return u.role === "admin" && u.is_active && activeAdmins <= 1;
  }

  function onDelete(u: AdminUser) {
    const message =
      `Delete ${u.email}? This also deletes their ${u.job_count} job(s), ` +
      `${u.template_count} template(s) and downloaded files. This cannot be undone.`;
    if (window.confirm(message)) deleteMutation.mutate(u.id);
  }

  return (
    <div>
      <h1>Users</h1>

      <div className="card">
        <label style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={appSettings?.allow_registration ?? false}
            disabled={!appSettings || settingsMutation.isPending}
            onChange={(e) => settingsMutation.mutate({ allow_registration: e.target.checked })}
          />
          Allow new users to register
        </label>
      </div>

      <input
        type="search"
        placeholder="Search by email"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        style={{ marginBottom: "1rem", maxWidth: 320 }}
      />

      {error && (
        <p className="error" role="alert">
          {error}
        </p>
      )}
      {isLoading && <p>Loading...</p>}
      {users && users.items.length === 0 && <p>No users found.</p>}
      {users && users.items.length > 0 && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Email</th>
                <th>Role</th>
                <th>Active</th>
                <th>Jobs</th>
                <th>Templates</th>
                <th>Joined</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users.items.map((u) =>
                editing === u.id ? (
                  <EditRow
                    key={u.id}
                    user={u}
                    saving={updateMutation.isPending}
                    onCancel={() => setEditing(null)}
                    onSave={(input) => updateMutation.mutate({ id: u.id, input })}
                  />
                ) : (
                  <tr key={u.id}>
                    <td>
                      {u.email}
                      {u.id === me?.id && <span className="muted"> (you)</span>}
                    </td>
                    <td>
                      <select
                        value={u.role}
                        disabled={isLastAdmin(u) || updateMutation.isPending}
                        title={isLastAdmin(u) ? "The last active admin must stay an admin" : ""}
                        onChange={(e) =>
                          updateMutation.mutate({
                            id: u.id,
                            input: { role: e.target.value as AdminUser["role"] },
                          })
                        }
                      >
                        <option value="user">User</option>
                        <option value="admin">Admin</option>
                      </select>
                    </td>
                    <td>
                      <input
                        type="checkbox"
                        checked={u.is_active}
                        disabled={isLastAdmin(u) || updateMutation.isPending}
                        title={isLastAdmin(u) ? "The last active admin cannot be disabled" : ""}
                        aria-label={`${u.email} active`}
                        onChange={(e) =>
                          updateMutation.mutate({ id: u.id, input: { is_active: e.target.checked } })
                        }
                      />
                    </td>
                    <td>{u.job_count}</td>
                    <td>{u.template_count}</td>
                    <td>{new Date(u.created_at).toLocaleDateString()}</td>
                    <td style={{ whiteSpace: "nowrap" }}>
                      <button className="secondary" onClick={() => setEditing(u.id)}>
                        Edit
                      </button>{" "}
                      {u.id !== me?.id && (
                        <button
                          className="secondary"
                          onClick={() => onDelete(u)}
                          disabled={deleteMutation.isPending}
                        >
                          Delete
                        </button>
                      )}
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function EditRow({
  user,
  saving,
  onCancel,
  onSave,
}: {
  user: AdminUser;
  saving: boolean;
  onCancel: () => void;
  onSave: (input: AdminUserUpdate) => void;
}) {
  const [email, setEmail] = useState(user.email);
  const [password, setPassword] = useState("");

  return (
    <tr>
      <td colSpan={7}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            onSave({
              ...(email !== user.email ? { email } : {}),
              ...(password ? { password } : {}),
            });
          }}
        >
          <label>
            Email
            <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </label>
          <label>
            New password (leave blank to keep the current one)
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              minLength={8}
              autoComplete="new-password"
            />
          </label>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <button className="primary" type="submit" disabled={saving}>
              {saving ? "Saving..." : "Save"}
            </button>
            <button className="secondary" type="button" onClick={onCancel}>
              Cancel
            </button>
          </div>
        </form>
      </td>
    </tr>
  );
}
