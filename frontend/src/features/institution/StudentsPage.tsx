import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";
import { useInstitution } from "./useInstitution";

const TABS = [["ALL", "All students"], ["PENDING", "Pending invitations"], ["IMPORT", "Import students"]] as const;
const blank = { email: "", first_name: "", last_name: "", student_id: "", department: "", program: "", cohort: "", graduation_year: "" };

function ImportPanel({ instId, onDone }: { instId: string; onDone: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [preview, setPreview] = useState<any>(null);
  const [result, setResult] = useState<any>(null);
  const form = () => { const fd = new FormData(); fd.append("file", file!); return fd; };
  const doPreview = useMutation({ mutationFn: () => api.post(`/institutions/${instId}/student-records/import/preview`, form()).then((r) => r.data),
    onSuccess: (d) => { setPreview(d); setResult(null); } });
  const doConfirm = useMutation({ mutationFn: () => api.post(`/institutions/${instId}/student-records/import/confirm`, form()).then((r) => r.data),
    onSuccess: (d) => { setResult(d); setPreview(null); onDone(); } });
  const shown = result ?? preview;
  return (
    <Card title="Import students from CSV">
      <p className="text-xs text-gray-500">Columns: student_id, first_name, last_name, <b>email</b> (required), department, program, cohort, graduation_year. Departments and cohorts must already exist. Each new email receives an invitation and chooses its own password.</p>
      <div className="flex gap-2 items-center">
        <input type="file" accept=".csv,text/csv" data-testid="csv-file" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(null); setResult(null); }} />
        <Button variant="secondary" onClick={() => doPreview.mutate()} disabled={!file || doPreview.isPending}>Preview</Button>
        {preview && preview.invite + preview.link_existing > 0 && (
          <Button onClick={() => doConfirm.mutate()} disabled={doConfirm.isPending}>{doConfirm.isPending ? "Importing…" : `Confirm import (${preview.invite + preview.link_existing} valid rows)`}</Button>)}
      </div>
      <ErrorBox error={doPreview.error || doConfirm.error} />
      {shown && (
        <div className="space-y-2" data-testid="import-summary">
          <p className="text-sm">{result ? "Imported: " : "Preview: "}{result ? `${result.invited} invited, ${result.linked} linked to existing accounts` : `${preview.invite} to invite, ${preview.link_existing} existing accounts to link`}, <b className={shown.errors ? "text-red-600" : ""}>{shown.errors} with errors</b> of {shown.total} rows.</p>
          <Table head={["Line", "Email", "Result"]}>{shown.rows.map((r: any) => (
            <tr key={r.line} className={r.action === "ERROR" ? "bg-red-50" : ""}><td className="py-1 pr-3">{r.line}</td><td className="pr-3">{r.email}</td>
              <td>{r.action === "ERROR" ? <span className="text-red-700">{r.error}</span> : r.action === "INVITE" ? "Invitation" : "Link existing account"}</td></tr>))}</Table>
        </div>)}
    </Card>
  );
}

export default function StudentsPage() {
  const { inst, isLoading } = useInstitution();
  const qc = useQueryClient();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>("ALL");
  const [f, setF] = useState(blank);
  const list = useQuery({ queryKey: ["student-records", inst?.id, tab], enabled: !!inst && tab !== "IMPORT",
    queryFn: () => api.get(`/institutions/${inst.id}/student-records`, { params: tab === "PENDING" ? { status: "PENDING" } : {} }).then((r) => r.data) });
  const counts = useQuery({ queryKey: ["student-records", inst?.id, "counts"], enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/student-records`, { params: { status: "NONE" } }).then((r) => r.data.counts) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["student-records"] }); qc.invalidateQueries({ queryKey: ["roster"] }); };
  const invite = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/student-records/invite`, f).then((r) => r.data),
    onSuccess: () => { setF(blank); refresh(); } });
  const act = useMutation({ mutationFn: ({ id, what }: { id: string; what: string }) => api.post(`/institutions/${inst.id}/student-records/${id}/${what}`), onSuccess: refresh });
  if (isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;
  const c = counts.data ?? {};
  const set = (k: keyof typeof blank) => (e: React.ChangeEvent<HTMLInputElement>) => setF({ ...f, [k]: e.target.value });
  return (
    <div className="max-w-6xl space-y-4">
      <h1 className="text-lg font-semibold">Students</h1>
      <div className="flex gap-2 text-sm">{TABS.map(([k, label]) => (
        <button key={k} onClick={() => setTab(k)} className={`px-3 py-1.5 rounded-md border ${tab === k ? "bg-gray-900 text-white border-gray-900" : "border-gray-300"}`}>
          {label}{k === "PENDING" && c.PENDING ? ` (${c.PENDING})` : ""}</button>))}
        <span className="ml-auto text-xs text-gray-500 self-center">Active {c.ACTIVE ?? 0} · Pending {c.PENDING ?? 0} · Disabled {c.DISABLED ?? 0}</span></div>
      {tab === "IMPORT" ? <ImportPanel instId={inst.id} onDone={refresh} /> : (
        <>
          <Card title="Invite a student">
            <div className="grid grid-cols-4 gap-2">
              <input className={inputCls} placeholder="Email *" value={f.email} onChange={set("email")} />
              <input className={inputCls} placeholder="First name" value={f.first_name} onChange={set("first_name")} />
              <input className={inputCls} placeholder="Last name" value={f.last_name} onChange={set("last_name")} />
              <input className={inputCls} placeholder="Student / registration ID" value={f.student_id} onChange={set("student_id")} />
              <input className={inputCls} placeholder="Department (existing)" value={f.department} onChange={set("department")} />
              <input className={inputCls} placeholder="Program" value={f.program} onChange={set("program")} />
              <input className={inputCls} placeholder="Cohort (existing)" value={f.cohort} onChange={set("cohort")} />
              <input className={inputCls} placeholder="Graduation year" value={f.graduation_year} onChange={set("graduation_year")} />
            </div>
            <div><Button onClick={() => invite.mutate()} disabled={!f.email || invite.isPending}>Send invitation</Button></div>
            <ErrorBox error={invite.error} />
          </Card>
          <Card title={tab === "PENDING" ? "Pending invitations" : "All students"}>
            {list.isLoading && <Loading />}
            {list.data && list.data.students.length === 0 && <Empty>{tab === "PENDING" ? "No pending invitations." : "No students yet. Invite one above or import a CSV."}</Empty>}
            {list.data && list.data.students.length > 0 && (
              <Table head={["Name", "Email", "ID", "Department", "Cohort", "Grad. year", "Status", ""]}>{list.data.students.map((s: any) => (
                <tr key={s.id}><td className="py-1 pr-3">{s.student_profile_id ? <Link className="underline" to={`/institution/institutions/${inst.id}/students/${s.student_profile_id}`}>{s.name ?? s.email}</Link> : (s.name ?? "—")}</td>
                  <td className="pr-3 text-xs">{s.email}</td><td className="pr-3">{s.student_code ?? "—"}</td><td className="pr-3">{s.department ?? "—"}</td>
                  <td className="pr-3">{s.cohort ?? "—"}</td><td className="pr-3">{s.graduation_year ?? "—"}</td>
                  <td className="pr-3"><Badge tone={s.status === "ACTIVE" ? "green" : s.status === "PENDING" ? "amber" : "gray"}>{s.status === "PENDING" ? "Pending invite" : s.status}</Badge></td>
                  <td className="space-x-1 whitespace-nowrap">
                    {s.status === "PENDING" && <Button variant="secondary" onClick={() => act.mutate({ id: s.id, what: "resend" })}>Resend invite</Button>}
                    {s.status !== "DISABLED" ? <Button variant="secondary" onClick={() => act.mutate({ id: s.id, what: "disable" })}>Disable</Button>
                      : <Button variant="secondary" onClick={() => act.mutate({ id: s.id, what: "enable" })}>Re-enable</Button>}</td></tr>))}</Table>)}
            <ErrorBox error={act.error} />
          </Card>
        </>)}
    </div>
  );
}
