import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";

function AddForm({ endpoint, fields, label }: { endpoint: string; fields: [string, string][]; label: string }) {
  const qc = useQueryClient();
  const [v, setV] = useState<Record<string, string>>({});
  const m = useMutation({
    mutationFn: () => {
      const body: Record<string, unknown> = {};
      for (const [k] of fields) if (v[k]) body[k] = k === "claimed_skill_names" ? v[k].split(",").map((s) => s.trim()) : ["start_year", "end_year"].includes(k) ? Number(v[k]) : k === "gpa" ? Number(v[k]) : v[k];
      return api.post(`/students/me/${endpoint}`, body);
    },
    onSuccess: () => { setV({}); qc.invalidateQueries({ queryKey: ["profile-full"] }); },
  });
  return (
    <div className="flex flex-wrap gap-2 items-end">
      {fields.map(([k, ph]) => <input key={k} className={`${inputCls} w-40`} placeholder={ph} value={v[k] ?? ""} onChange={(e) => setV({ ...v, [k]: e.target.value })} />)}
      <Button variant="secondary" onClick={() => m.mutate()} disabled={m.isPending || !v[fields[0][0]]}>Add {label}</Button>
      <ErrorBox error={m.error} />
    </div>
  );
}

export default function ProfilePage() {
  const qc = useQueryClient();
  const full = useQuery({
    queryKey: ["profile-full"], queryFn: () => api.get("/students/me/full").then((r) => r.data),
    refetchInterval: (q) => {
      const pr = (q.state.data as any)?.profile;
      return pr?.resume_document_id && ["PENDING", "PROCESSING"].includes(pr.resume_parse_status) ? 3000 : false;
    },
  });
  const p = full.data?.profile;
  const claims = useQuery({ queryKey: ["claims", p?.id, p?.resume_parse_status], enabled: !!p?.id,
    queryFn: () => api.get(`/evidence/students/${p.id}/evidence`).then((r) => r.data.filter((e: any) => e.source_type === "RESUME_CLAIM")) });
  const [basics, setBasics] = useState({ headline: "", bio: "", location: "" });
  useEffect(() => { if (p) setBasics({ headline: p.headline ?? "", bio: p.bio ?? "", location: p.location ?? "" }); }, [p?.id]); // eslint-disable-line
  const saveBasics = useMutation({ mutationFn: () => api.put("/students/me", basics), onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-full"] }) });
  const upload = useMutation({
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api.post("/students/me/resume", fd); },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["profile-full"] }),
  });

  if (full.isLoading) return <Loading />;
  if (full.error) return <ErrorBox error={full.error} onRetry={full.refetch} />;

  return (
    <div className="max-w-4xl space-y-5">
      <h1 className="text-lg font-semibold">Profile</h1>
      <Card title="About">
        <div className="grid grid-cols-2 gap-2">
          <input className={inputCls} placeholder="Headline" value={basics.headline} onChange={(e) => setBasics({ ...basics, headline: e.target.value })} />
          <input className={inputCls} placeholder="Location" value={basics.location} onChange={(e) => setBasics({ ...basics, location: e.target.value })} />
        </div>
        <textarea className={inputCls} rows={2} placeholder="Bio" value={basics.bio} onChange={(e) => setBasics({ ...basics, bio: e.target.value })} />
        <Button variant="secondary" onClick={() => saveBasics.mutate()} disabled={saveBasics.isPending}>{saveBasics.isSuccess ? "Saved" : "Save"}</Button>
        <ErrorBox error={saveBasics.error} />
      </Card>

      <Card title="Resume" actions={<Badge>{p?.resume_document_id ? p.resume_parse_status : "Not uploaded"}</Badge>}>
        <input type="file" accept=".pdf,.docx,.txt" onChange={(e) => e.target.files?.[0] && upload.mutate(e.target.files[0])} className="text-sm" />
        {upload.isPending && <p className="text-xs text-amber-700">Uploading…</p>}
        <ErrorBox error={upload.error} />
        {p?.resume_parse_status === "FAILED" && <p className="text-xs text-red-600">Resume processing failed — upload again to retry.</p>}
        <p className="text-xs text-gray-500">Skills found in your resume are stored as <b>unverified claims</b>. They help decide what to assess but count 0 toward your verified skill levels.</p>
        {(claims.data ?? []).length > 0 && (
          <div className="flex flex-wrap gap-1">{claims.data.map((c: any) => <Badge key={c.id} tone="gray">{`${c.skill_name} · claim`}</Badge>)}</div>
        )}
      </Card>

      <Card title="Education">
        {full.data.education.length === 0 ? <Empty>None added.</Empty> : (
          <Table head={["Institution", "Degree", "Field", "Years"]}>{full.data.education.map((e: any) => (
            <tr key={e.id}><td className="py-1 pr-3">{e.institution_name}</td><td className="pr-3">{e.degree}</td><td className="pr-3">{e.field_of_study}</td><td>{e.start_year}–{e.end_year}</td></tr>))}
          </Table>)}
        <AddForm endpoint="education" label="education" fields={[["institution_name", "Institution"], ["degree", "Degree"], ["field_of_study", "Field"], ["start_year", "Start year"], ["end_year", "End year"]]} />
      </Card>
      <Card title="Experience">
        {full.data.experience.length === 0 ? <Empty>None added.</Empty> : full.data.experience.map((e: any) => <p key={e.id} className="text-sm"><b>{e.title}</b> · {e.company_name} — <span className="text-gray-600">{e.description}</span></p>)}
        <AddForm endpoint="experience" label="experience" fields={[["company_name", "Company"], ["title", "Title"], ["description", "Description"]]} />
      </Card>
      <Card title="Projects">
        {full.data.projects.length === 0 ? <Empty>None added.</Empty> : full.data.projects.map((e: any) => <p key={e.id} className="text-sm"><b>{e.title}</b> — <span className="text-gray-600">{e.description}</span> {(e.claimed_skill_names ?? []).join(", ")}</p>)}
        <AddForm endpoint="projects" label="project" fields={[["title", "Title"], ["description", "Description"], ["url", "URL"], ["claimed_skill_names", "Skills (comma separated)"]]} />
      </Card>
      <Card title="Certifications">
        {full.data.certifications.length === 0 ? <Empty>None added.</Empty> : full.data.certifications.map((e: any) => <p key={e.id} className="text-sm"><b>{e.name}</b> · {e.issuer}</p>)}
        <AddForm endpoint="certifications" label="certification" fields={[["name", "Name"], ["issuer", "Issuer"], ["credential_url", "Credential URL"]]} />
      </Card>
    </div>
  );
}
