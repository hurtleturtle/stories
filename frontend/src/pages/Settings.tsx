import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { getSettings, updateSettings } from "../api/endpoints";

export default function Settings() {
  const queryClient = useQueryClient();
  const { data } = useQuery({ queryKey: ["settings"], queryFn: getSettings });

  const [kindleAddress, setKindleAddress] = useState("");
  const [emailFrom, setEmailFrom] = useState("");
  const [smtpHost, setSmtpHost] = useState("smtp.gmail.com");
  const [smtpPort, setSmtpPort] = useState(465);
  const [smtpUsername, setSmtpUsername] = useState("");
  const [smtpPassword, setSmtpPassword] = useState("");
  const [autoSend, setAutoSend] = useState(false);

  useEffect(() => {
    if (!data) return;
    setKindleAddress(data.kindle_address ?? "");
    setEmailFrom(data.email_from ?? "");
    setSmtpHost(data.smtp_host);
    setSmtpPort(data.smtp_port);
    setSmtpUsername(data.smtp_username ?? "");
    setAutoSend(data.auto_send_default);
  }, [data]);

  const mutation = useMutation({
    mutationFn: () =>
      updateSettings({
        kindle_address: kindleAddress || undefined,
        email_from: emailFrom || undefined,
        smtp_host: smtpHost,
        smtp_port: smtpPort,
        smtp_username: smtpUsername || undefined,
        smtp_password: smtpPassword || undefined,
        auto_send_default: autoSend,
      }),
    onSuccess: () => {
      setSmtpPassword("");
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    },
  });

  return (
    <div>
      <h1>Settings</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          Kindle email address
          <input value={kindleAddress} onChange={(e) => setKindleAddress(e.target.value)} />
        </label>
        <label>
          Send-from email address
          <input
            type="email"
            value={emailFrom}
            onChange={(e) => setEmailFrom(e.target.value)}
          />
        </label>
        <label>
          SMTP host
          <input value={smtpHost} onChange={(e) => setSmtpHost(e.target.value)} />
        </label>
        <label>
          SMTP port
          <input
            type="number"
            value={smtpPort}
            onChange={(e) => setSmtpPort(Number(e.target.value))}
          />
        </label>
        <label>
          SMTP username
          <input value={smtpUsername} onChange={(e) => setSmtpUsername(e.target.value)} />
        </label>
        <label>
          SMTP password {data?.smtp_password_set && "(already set — leave blank to keep)"}
          <input
            type="password"
            value={smtpPassword}
            onChange={(e) => setSmtpPassword(e.target.value)}
          />
        </label>
        <label style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
          <input
            type="checkbox"
            checked={autoSend}
            onChange={(e) => setAutoSend(e.target.checked)}
          />
          Email new jobs to Kindle by default
        </label>
        <button className="primary" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </form>
    </div>
  );
}
