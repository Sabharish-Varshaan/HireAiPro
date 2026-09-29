import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";
import { useInstitution } from "./useInstitution";

export default function StructurePage() {
  const { inst, isLoading } = useInstitution();
  const qc = useQueryClient();
  const structure = useQuery({ queryKey: ["structure", inst?.id], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/structure`).then((r) => r.data) });
  const [dep, setDep] = useState("");
  const [cohort, setCohort] = useState({ name: "", department_id: "", graduation_year: "" });
  const inv = () => qc.invalidateQueries({ queryKey: ["structure"] });
  const addDep = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/departments`, { name: dep }), onSuccess: () => { setDep(""); inv(); } });
  const addCohort = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/cohorts`, {
    name: cohort.name, department_id: cohort.department_id || null, graduation_year: cohort.graduation_year ? Number(cohort.graduation_year) : null }),
    onSuccess: () => { setCohort({ name: "", department_id: "", graduation_year: "" }); inv(); } });
  if (isLoading || structure.isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;
  const deps = structure.data?.departments ?? [];
  const cohorts = structure.data?.cohorts ?? [];
  const depName = (id: string) => deps.find((d: any) => d.id === id)?.name ?? "—";
  return (
    <div className="max-w-4xl space-y-5">
      <h1 className="text-lg font-semibold">Academic structure</h1>
      <p className="text-xs text-gray-500">Departments and cohorts are labels used to organize students and to target opportunities. Students are added under Students.</p>
      <Card title="Departments">
        <div className="flex gap-2"><input className={inputCls} placeholder="New department" value={dep} onChange={(e) => setDep(e.target.value)} />
          <Button variant="secondary" onClick={() => addDep.mutate()} disabled={!dep.trim() || addDep.isPending}>Add department</Button></div>
        {deps.length === 0 ? <Empty>No departments yet.</Empty> : <ul className="text-sm list-disc pl-5">{deps.map((d: any) => <li key={d.id}>{d.name}</li>)}</ul>}
      </Card>
      <Card title="Cohorts">
        <div className="flex gap-2">
          <input className={inputCls} placeholder="New cohort (e.g. CSE 2027)" value={cohort.name} onChange={(e) => setCohort({ ...cohort, name: e.target.value })} />
          <select className={inputCls} value={cohort.department_id} onChange={(e) => setCohort({ ...cohort, department_id: e.target.value })}>
            <option value="">No department</option>{deps.map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
          <input className={`${inputCls} w-28`} placeholder="Grad year" value={cohort.graduation_year} onChange={(e) => setCohort({ ...cohort, graduation_year: e.target.value })} />
          <Button variant="secondary" onClick={() => addCohort.mutate()} disabled={!cohort.name.trim() || addCohort.isPending}>Add cohort</Button></div>
        {cohorts.length === 0 ? <Empty>No cohorts yet.</Empty> : (
          <Table head={["Cohort", "Department", "Graduation year"]}>{cohorts.map((c: any) => (
            <tr key={c.id}><td className="py-1 pr-3">{c.name}</td><td className="pr-3">{depName(c.department_id)}</td><td>{c.graduation_year ?? "—"}</td></tr>))}</Table>)}
      </Card>
      <ErrorBox error={addDep.error || addCohort.error} />
    </div>
  );
}
