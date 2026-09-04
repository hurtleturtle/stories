import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { createTemplate, listTemplates, updateTemplate } from "../api/endpoints";
import type { TemplateInput } from "../api/types";

const EMPTY: TemplateInput = {
  name: "",
  site_hostname: "",
  container: "",
  next_selector: "",
  detect_title: "",
  style: "white-style.css",
  scripts: [],
  ebook_type: "epub",
};

export default function TemplateForm() {
  const { id } = useParams<{ id: string }>();
  const isNew = !id || id === "new";
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const { data: templates } = useQuery({ queryKey: ["templates"], queryFn: listTemplates });
  const existing = !isNew ? templates?.find((t) => t.id === id) : undefined;

  const [form, setForm] = useState<TemplateInput>(EMPTY);

  useEffect(() => {
    if (existing) {
      setForm({
        name: existing.name,
        site_hostname: existing.site_hostname ?? "",
        container: existing.container,
        next_selector: existing.next_selector,
        detect_title: existing.detect_title ?? "",
        style: existing.style,
        scripts: existing.scripts,
        ebook_type: existing.ebook_type,
      });
    }
  }, [existing]);

  const mutation = useMutation({
    mutationFn: () => (isNew ? createTemplate(form) : updateTemplate(id!, form)),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["templates"] });
      navigate("/templates");
    },
  });

  function set<K extends keyof TemplateInput>(key: K, value: TemplateInput[K]) {
    setForm((f) => ({ ...f, [key]: value }));
  }

  return (
    <div>
      <h1>{isNew ? "New template" : `Edit ${existing?.name ?? ""}`}</h1>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          mutation.mutate();
        }}
      >
        <label>
          Name
          <input value={form.name} onChange={(e) => set("name", e.target.value)} required />
        </label>
        <label>
          Site hostname (optional)
          <input
            value={form.site_hostname ?? ""}
            onChange={(e) => set("site_hostname", e.target.value)}
          />
        </label>
        <label>
          Container CSS selector
          <input
            value={form.container}
            onChange={(e) => set("container", e.target.value)}
            required
          />
        </label>
        <label>
          Next-chapter CSS selector
          <input
            value={form.next_selector}
            onChange={(e) => set("next_selector", e.target.value)}
            required
          />
        </label>
        <label>
          Chapter title CSS selector (optional)
          <input
            value={form.detect_title ?? ""}
            onChange={(e) => set("detect_title", e.target.value)}
          />
        </label>
        <label>
          Stylesheet filename
          <input value={form.style} onChange={(e) => set("style", e.target.value)} />
        </label>
        <label>
          Ebook type
          <select value={form.ebook_type} onChange={(e) => set("ebook_type", e.target.value)}>
            <option value="epub">epub</option>
            <option value="mobi">mobi</option>
          </select>
        </label>
        <button className="primary" type="submit" disabled={mutation.isPending}>
          {mutation.isPending ? "Saving..." : "Save"}
        </button>
      </form>
    </div>
  );
}
