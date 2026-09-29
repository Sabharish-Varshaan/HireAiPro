import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, inputCls } from "../../components/ui";
import { useInstitution } from "./useInstitution";

function Review({ inst, op, structure }: { inst: any; op: any; structure: any }) {
  const qc = useQueryClient();
  const [deps, setDeps] = useState<string[]>([]);
  const [cohorts, setCohorts] = useState<string[]>([]);
  const [years, setYears] = useState("");
  const [note, setNote] = useState("");
  const done = () => qc.invalidateQueries({ queryKey: ["opportunities"] });
  const approve = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/opportunities/${op.job_id}/approve`, {
    department_ids: deps, cohort_ids: cohorts, graduation_years: years.split(",").map((y) => y.trim()).filter(Boolean).map(Number) }), onSuccess: done });
  const reject = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/opportunities/${op.job_id}/reject`, { note }), onSuccess: done });
  const toggle = (arr: string[], set: (v: string[]) => void, id: string) => set(arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);
  const nameOf = (list: any[], id: string) => list.find((x) => x.id === id)?.name ?? id;
  return (
    <Card title={`${op.title} · ${op.company}`} actions={<Badge>{op.status}</Badge>}>
      <p className="text-xs text-gray-500">{[op.location, op.employment_type].filter(Boolean).join(" · ")}</p>
      {op.description && <p className="text-xs text-gray-600 whitespace-pre-wrap max-h-32 overflow-auto border border-gray-100 rounded p-2">{op.description}</p>}
      <div className="flex flex-wrap gap-1">{op.skills.map((s: any) => <Badge key={s.name} tone={s.type === "required" ? "blue" : "gray"}>{s.name}</Badge>)}</div>
      {op.status === "PENDING" ? (
        <div className="space-y-2 text-sm">
          <p className="text-xs font-medium">Who may see and apply? Leave a group empty to allow everyone in it.</p>
          <div className="flex flex-wrap gap-3">
            <div><p className="text-xs text-gray-500">Departments</p>{structure.departments.length === 0 && <span className="text-xs text-gray-400">none defined</span>}
              {structure.departments.map((d: any) => <label key={d.id} className="block text-xs"><input type="checkbox" checked={deps.includes(d.id)} onChange={() => toggle(deps, setDeps, d.id)} /> {d.name}</label>)}</div>
            <div><p className="text-xs text-gray-500">Cohorts</p>{structure.cohorts.length === 0 && <span className="text-xs text-gray-400">none defined</span>}
              {structure.cohorts.map((c: any) => <label key={c.id} className="block text-xs"><input type="checkbox" checked={cohorts.includes(c.id)} onChange={() => toggle(cohorts, setCohorts, c.id)} /> {c.name}</label>)}</div>
            <div><p className="text-xs text-gray-500">Graduation years (comma separated)</p><input className={inputCls} placeholder="2026, 2027" value={years} onChange={(e) => setYears(e.target.value)} /></div>
          </div>
          <div className="flex gap-2 items-center">
            <Button onClick={() => approve.mutate()} disabled={approve.isPending}>Approve and distribute</Button>
            <input className={inputCls} placeholder="Reason for rejection" value={note} onChange={(e) => setNote(e.target.value)} />
            <Button variant="danger" onClick={() => reject.mutate()} disabled={reject.isPending || note.trim().length < 3}>Reject</Button>
          </div>
          <ErrorBox error={approve.error || reject.error} />
        </div>
      ) : op.status === "APPROVED" ? (
        <p className="text-xs text-gray-600">Visible to: departments {(op.eligibility?.department_ids ?? []).map((i: string) => nameOf(structure.departments, i)).join(", ") || "all"} · cohorts {(op.eligibility?.cohort_ids ?? []).map((i: string) => nameOf(structure.cohorts, i)).join(", ") || "all"} · graduation years {(op.eligibility?.graduation_years ?? []).join(", ") || "all"}</p>
      ) : <p className="text-xs text-gray-600">Rejected: {op.note}</p>}
    </Card>
  );
}

export default function OpportunitiesPage() {
  const { inst, isLoading } = useInstitution();
  const [tab, setTab] = useState<"PENDING" | "APPROVED" | "REJECTED">("PENDING");
  const ops = useQuery({ queryKey: ["opportunities", inst?.id, tab], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/opportunities`, { params: { status: tab } }).then((r) => r.data) });
  const structure = useQuery({ queryKey: ["structure", inst?.id], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/structure`).then((r) => r.data) });
  if (isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;
  return (
    <div className="max-w-4xl space-y-4">
      <h1 className="text-lg font-semibold">Opportunities</h1>
      <p className="text-xs text-gray-500">Companies that target {inst.name} submit jobs here. Only approved jobs reach students, and only the students you allow.</p>
      <div className="flex gap-2 text-sm">{(["PENDING", "APPROVED", "REJECTED"] as const).map((k) => (
        <button key={k} onClick={() => setTab(k)} className={`px-3 py-1.5 rounded-md border ${tab === k ? "bg-gray-900 text-white border-gray-900" : "border-gray-300"}`}>{k[0] + k.slice(1).toLowerCase()}</button>))}</div>
      {ops.isLoading && <Loading />}
      {ops.data?.length === 0 && <Empty>No {tab.toLowerCase()} opportunities.</Empty>}
      {structure.data && (ops.data ?? []).map((op: any) => <Review key={op.job_id} inst={inst} op={op} structure={structure.data} />)}
    </div>
  );
}
