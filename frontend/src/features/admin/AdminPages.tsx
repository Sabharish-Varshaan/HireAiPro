import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Fragment, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";

export function AdminSkills() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<string | null>(null);
  const [nw, setNw] = useState({ canonical_name: "", category: "", description: "" });
  const [alias, setAlias] = useState("");
  const [rel, setRel] = useState({ to: "", relation_type: "RELATED_TO" });
  const list = useQuery({ queryKey: ["admin-skills", q], queryFn: () => api.get("/admin/skills", { params: { q, include_inactive: true, limit: 50 } }).then((r) => r.data) });
  const detail = useQuery({ queryKey: ["admin-skill", sel], enabled: !!sel, queryFn: () => api.get(`/admin/skills/${sel}`).then((r) => r.data) });
  const target = useQuery({ queryKey: ["skill-target", rel.to], enabled: rel.to.length > 1, queryFn: () => api.get("/skills", { params: { q: rel.to, limit: 5 } }).then((r) => r.data) });
  const inv = () => { qc.invalidateQueries({ queryKey: ["admin-skills"] }); qc.invalidateQueries({ queryKey: ["admin-skill"] }); };
  const create = useMutation({ mutationFn: () => api.post("/admin/skills", nw), onSuccess: (r) => { setNw({ canonical_name: "", category: "", description: "" }); setSel(r.data.id); inv(); } });
  const patch = useMutation({ mutationFn: (b: any) => api.patch(`/admin/skills/${sel}`, b), onSuccess: inv });
  const addAlias = useMutation({ mutationFn: () => api.post(`/admin/skills/${sel}/aliases`, { alias }), onSuccess: () => { setAlias(""); inv(); } });
  const delAlias = useMutation({ mutationFn: (id: string) => api.delete(`/admin/aliases/${id}`), onSuccess: inv });
  const addRel = useMutation({ mutationFn: (to_skill_id: string) => api.post(`/admin/skills/${sel}/relationships`, { to_skill_id, relation_type: rel.relation_type }), onSuccess: () => { setRel({ ...rel, to: "" }); inv(); } });
  const delRel = useMutation({ mutationFn: (id: string) => api.delete(`/admin/relationships/${id}`), onSuccess: inv });
  const d = detail.data;
  return (
    <div className="max-w-6xl grid md:grid-cols-2 gap-4">
      <div className="space-y-4">
        <Card title="Create canonical skill">
          <input className={inputCls} placeholder="Canonical name" value={nw.canonical_name} onChange={(e) => setNw({ ...nw, canonical_name: e.target.value })} />
          <input className={inputCls} placeholder="Category" value={nw.category} onChange={(e) => setNw({ ...nw, category: e.target.value })} />
          <Button onClick={() => create.mutate()} disabled={!nw.canonical_name || !nw.category}>Create</Button>
          <ErrorBox error={create.error} />
        </Card>
        <Card title={`Skills (${list.data?.total ?? "…"})`}>
          <input className={inputCls} placeholder="Search name or alias" value={q} onChange={(e) => setQ(e.target.value)} />
          {list.isLoading && <Loading />}
          <div className="max-h-[28rem] overflow-auto divide-y divide-gray-100">
            {(list.data?.items ?? []).map((s: any) => (
              <button key={s.id} onClick={() => setSel(s.id)} className={`block w-full text-left py-1.5 text-sm ${sel === s.id ? "font-semibold" : ""}`}>
                {s.canonical_name} <span className="text-xs text-gray-400">{s.category}</span> {!s.is_active && <Badge tone="gray">inactive</Badge>}
              </button>))}
          </div>
        </Card>
      </div>
      <Card title={d ? d.canonical_name : "Select a skill"}>
        {!d ? <Empty>Choose a skill to inspect or edit.</Empty> : (
          <div className="space-y-3 text-sm">
            <div className="flex gap-2 items-center">
              <input className={inputCls} defaultValue={d.description ?? ""} placeholder="Description" onBlur={(e) => e.target.value !== (d.description ?? "") && patch.mutate({ description: e.target.value })} />
              <Button variant={d.is_active ? "danger" : "secondary"} onClick={() => patch.mutate({ is_active: !d.is_active })}>{d.is_active ? "Deactivate" : "Reactivate"}</Button>
            </div>
            <div>
              <p className="text-xs font-medium mb-1">Aliases</p>
              <div className="flex flex-wrap gap-1">{d.aliases.map((a: any) => <span key={a.id} className="text-xs border rounded px-1">{a.alias} <button onClick={() => delAlias.mutate(a.id)} className="text-red-600">×</button></span>)}</div>
              <div className="flex gap-2 mt-1"><input className={inputCls} placeholder="New alias" value={alias} onChange={(e) => setAlias(e.target.value)} />
                <Button variant="secondary" onClick={() => addAlias.mutate()} disabled={!alias}>Add</Button></div>
            </div>
            <div>
              <p className="text-xs font-medium mb-1">Relationships</p>
              {d.relationships.map((r: any) => <p key={r.id} className="text-xs">{r.from} <b>{r.type}</b> {r.to} <button className="text-red-600" onClick={() => delRel.mutate(r.id)}>remove</button></p>)}
              <div className="flex gap-2 mt-1">
                <select className={`${inputCls} w-44`} value={rel.relation_type} onChange={(e) => setRel({ ...rel, relation_type: e.target.value })}>
                  <option>RELATED_TO</option><option>PREREQUISITE_OF</option><option>PARENT_OF</option></select>
                <input className={inputCls} placeholder="Target skill" value={rel.to} onChange={(e) => setRel({ ...rel, to: e.target.value })} />
              </div>
              {(target.data ?? []).map((s: any) => <button key={s.id} className="block text-xs underline" onClick={() => addRel.mutate(s.id)}>{d.canonical_name} {rel.relation_type} {s.canonical_name}</button>)}
            </div>
            <ErrorBox error={patch.error || addAlias.error || addRel.error || delAlias.error || delRel.error} />
          </div>)}
      </Card>
    </div>
  );
}

export function AdminKnowledge() {
  const qc = useQueryClient();
  const [f, setF] = useState({ title: "", source_uri: "", skills: "" });
  const list = useQuery({ queryKey: ["knowledge"], queryFn: () => api.get("/knowledge/sources").then((r) => r.data), refetchInterval: 5000 });
  const reg = useMutation({ mutationFn: () => api.post("/knowledge/sources", { title: f.title, source_type: "APPROVED_URL", source_uri: f.source_uri,
    skills: f.skills.split(",").map((s) => s.trim()).filter(Boolean), visibility: "PLATFORM_PUBLIC" }), onSuccess: () => { setF({ title: "", source_uri: "", skills: "" }); qc.invalidateQueries({ queryKey: ["knowledge"] }); } });
  const retry = useMutation({ mutationFn: (id: string) => api.post(`/knowledge/sources/${id}/ingest`), onSuccess: () => qc.invalidateQueries({ queryKey: ["knowledge"] }) });
  return (
    <div className="max-w-6xl space-y-4">
      <Card title="Register approved documentation (official-docs hosts only)">
        <div className="grid grid-cols-3 gap-2">
          <input className={inputCls} placeholder="Title" value={f.title} onChange={(e) => setF({ ...f, title: e.target.value })} />
          <input className={inputCls} placeholder="https://… (approved host)" value={f.source_uri} onChange={(e) => setF({ ...f, source_uri: e.target.value })} />
          <input className={inputCls} placeholder="Skills, comma separated" value={f.skills} onChange={(e) => setF({ ...f, skills: e.target.value })} />
        </div>
        <Button onClick={() => reg.mutate()} disabled={!f.title || !f.source_uri || !f.skills}>Register & ingest</Button>
        <ErrorBox error={reg.error || retry.error} />
      </Card>
      <Card title="Knowledge sources">
        {list.isLoading && <Loading />}
        <Table head={["Title", "Skills", "Visibility", "Status", "Chunks", "Version", "Ingested", "Error", ""]}>
          {(list.data ?? []).map((s: any) => (
            <tr key={s.id} className="align-top">
              <td className="py-1 pr-3"><a className="underline" href={s.source_uri.startsWith("http") ? s.source_uri : undefined} target="_blank" rel="noreferrer">{s.title}</a></td>
              <td className="pr-3 text-xs">{s.skills.join(", ")}</td><td className="pr-3 text-xs">{s.visibility}</td><td className="pr-3"><Badge>{s.status}</Badge></td>
              <td className="pr-3">{s.chunk_count}</td><td className="pr-3">v{s.document_version}</td>
              <td className="pr-3 text-xs">{s.last_ingested_at ? new Date(s.last_ingested_at).toLocaleString() : "—"}</td>
              <td className="pr-3 text-xs text-red-600 max-w-xs">{s.error ?? ""}</td>
              <td><button className="text-xs underline" onClick={() => retry.mutate(s.id)}>{s.status === "FAILED" ? "retry" : "re-ingest"}</button></td>
            </tr>))}
        </Table>
      </Card>
    </div>
  );
}

export function AdminRuns() {
  const [open, setOpen] = useState<string | null>(null);
  const ai = useQuery({ queryKey: ["ai-runs-full"], queryFn: () => api.get("/admin/ai-runs", { params: { limit: 150 } }).then((r) => r.data) });
  const ag = useQuery({ queryKey: ["agent-runs-full"], queryFn: () => api.get("/admin/agent-runs").then((r) => r.data) });
  return (
    <div className="max-w-6xl space-y-4">
      <Card title="Agent runs">
        <ErrorBox error={ag.error} />
        <Table head={["When", "Agent", "Status", "Fallback", "Tools", "Error"]}>
          {(ag.data ?? []).slice(0, 60).map((r: any) => (
            <Fragment key={r.id}>
              <tr className="cursor-pointer align-top" onClick={() => setOpen(open === r.id ? null : r.id)}>
                <td className="py-1 pr-3 text-xs">{r.started_at ? new Date(r.started_at).toLocaleString() : ""}</td><td className="pr-3">{r.agent_type}</td>
                <td className="pr-3"><Badge>{r.status}</Badge></td><td className="pr-3">{r.used_fallback ? <Badge tone="amber">deterministic fallback</Badge> : "no"}</td>
                <td className="pr-3">{r.tool_calls.length}</td><td className="text-xs text-red-600 max-w-sm">{r.error?.slice(0, 160)}</td>
              </tr>
              {open === r.id && <tr><td colSpan={6} className="text-xs text-gray-600 pb-2">{r.tool_calls.map((c: any) => c.tool).join(" → ")}</td></tr>}
            </Fragment>))}
        </Table>
      </Card>
      <Card title="AI runs">
        <ErrorBox error={ai.error} />
        <Table head={["When", "Task", "Provider · model", "Status", "Latency", "Tokens in/out", "Cost", "Retries", "Fallback / error"]}>
          {(ai.data ?? []).map((r: any) => (
            <tr key={r.id} className="align-top">
              <td className="py-1 pr-3 text-xs">{new Date(r.created_at).toLocaleString()}</td><td className="pr-3 text-xs">{r.task_type}</td>
              <td className="pr-3 text-xs">{r.provider} · {r.model}</td><td className="pr-3"><Badge>{r.status}</Badge></td>
              <td className="pr-3 text-xs">{r.latency_ms ? `${r.latency_ms} ms` : "—"}</td><td className="pr-3 text-xs">{r.input_tokens ?? 0}/{r.output_tokens ?? 0}</td>
              <td className="pr-3 text-xs">${(r.estimated_cost_usd ?? 0).toFixed(6)}</td><td className="pr-3 text-xs">{r.retry_count ?? 0}</td>
              <td className="text-xs text-gray-500 max-w-xs">{(r.fallback_reason ?? r.error ?? "").slice(0, 140)}</td>
            </tr>))}
        </Table>
      </Card>
    </div>
  );
}

export function AdminJobs() {
  const qc = useQueryClient();
  const [status, setStatus] = useState("FAILED");
  const jobs = useQuery({ queryKey: ["bg-jobs", status], queryFn: () => api.get("/admin/jobs", { params: status ? { status } : {} }).then((r) => r.data) });
  const retry = useMutation({ mutationFn: (id: string) => api.post(`/admin/jobs/${id}/retry`), onSuccess: () => qc.invalidateQueries({ queryKey: ["bg-jobs"] }) });
  return (
    <Card title="Background jobs" actions={<select className={`${inputCls} w-40`} value={status} onChange={(e) => setStatus(e.target.value)}>
      <option value="FAILED">Failed</option><option value="">All</option><option value="RUNNING">Running</option><option value="COMPLETED">Completed</option></select>}>
      <ErrorBox error={jobs.error || retry.error} />
      {jobs.data?.length === 0 && <Empty>No jobs in this state.</Empty>}
      <Table head={["Job", "Type", "Status", "Attempts", "Error", "Updated", ""]}>
        {(jobs.data ?? []).map((j: any) => (
          <tr key={j.id} className="align-top"><td className="py-1 pr-3 text-xs">{j.job_key}</td><td className="pr-3 text-xs">{j.job_type}</td>
            <td className="pr-3"><Badge>{j.status}</Badge></td><td className="pr-3">{j.attempts}</td>
            <td className="pr-3 text-xs text-red-600 max-w-sm">{(j.error ?? "").split("\n")[0]}</td><td className="pr-3 text-xs">{new Date(j.updated_at).toLocaleString()}</td>
            <td>{j.status === "FAILED" && <button className="text-xs underline" onClick={() => retry.mutate(j.id)}>retry</button>}</td></tr>))}
      </Table>
    </Card>
  );
}

export function AdminAudit() {
  const [action, setAction] = useState("");
  const actions = useQuery({ queryKey: ["audit-actions"], queryFn: () => api.get("/admin/audit-actions").then((r) => r.data) });
  const logs = useQuery({ queryKey: ["audit", action], queryFn: () => api.get("/admin/audit-logs", { params: action ? { action } : {} }).then((r) => r.data) });
  return (
    <Card title="Audit log" actions={<select className={`${inputCls} w-64`} value={action} onChange={(e) => setAction(e.target.value)}>
      <option value="">All actions</option>{(actions.data ?? []).map((a: any) => <option key={a.action} value={a.action}>{a.action} ({a.count})</option>)}</select>}>
      <ErrorBox error={logs.error} />
      <Table head={["When", "Actor", "Action", "Entity", "Details"]}>
        {(logs.data ?? []).map((e: any) => (
          <tr key={e.id} className="align-top"><td className="py-1 pr-3 text-xs">{new Date(e.created_at).toLocaleString()}</td><td className="pr-3 text-xs">{e.actor}</td>
            <td className="pr-3 text-xs">{e.action}</td><td className="pr-3 text-xs">{e.entity_type} {String(e.entity_id ?? "").slice(0, 8)}</td>
            <td className="text-xs text-gray-500">{e.metadata ? JSON.stringify(e.metadata).slice(0, 140) : ""}</td></tr>))}
      </Table>
    </Card>
  );
}

export function AdminUsers() {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const users = useQuery({ queryKey: ["admin-users"], queryFn: () => api.get("/admin/users").then((r) => r.data) });
  const toggle = useMutation({
    mutationFn: ({ id, is_active }: { id: string; is_active: boolean }) => api.patch(`/admin/users/${id}`, { is_active }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["admin-users"] }),
  });
  const rows = (users.data ?? []).filter((u: any) => !q || `${u.full_name} ${u.email}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <Card title="Users" actions={<input className={`${inputCls} w-64`} placeholder="Search name or email" value={q} onChange={(e) => setQ(e.target.value)} />}>
      {users.isLoading && <Loading />}
      <ErrorBox error={users.error || toggle.error} onRetry={users.refetch} />
      <Table head={["Name", "Email", "Role", "Status", ""]}>
        {rows.map((u: any) => (
          <tr key={u.id}><td className="py-1 pr-3">{u.full_name}</td><td className="pr-3 text-xs">{u.email}</td><td className="pr-3 text-xs">{u.role}</td>
            <td className="pr-3"><Badge tone={u.is_active ? "green" : "red"}>{u.is_active ? "active" : "deactivated"}</Badge></td>
            <td><Button variant={u.is_active ? "danger" : "secondary"} disabled={toggle.isPending}
              onClick={() => toggle.mutate({ id: u.id, is_active: !u.is_active })}>{u.is_active ? "Deactivate" : "Reactivate"}</Button></td></tr>
        ))}
      </Table>
      {!users.isLoading && rows.length === 0 && <Empty>No users match.</Empty>}
    </Card>
  );
}
