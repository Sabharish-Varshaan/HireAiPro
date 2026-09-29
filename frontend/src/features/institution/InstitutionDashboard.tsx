import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Button, Card, Empty, ErrorBox, Loading, Table, inputCls, pct } from "../../components/ui";

export default function InstitutionDashboard() {
  const mine = useQuery({ queryKey: ["my-institutions"], queryFn: () => api.get("/institutions/mine").then((r) => r.data) });
  const inst = mine.data?.[0];
  const [f, setF] = useState({ department_id: "", cohort_id: "" });
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v));
  const structure = useQuery({ queryKey: ["structure", inst?.id], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/structure`).then((r) => r.data) });
  const roster = useQuery({ queryKey: ["roster", inst?.id, params], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/roster`, { params }).then((r) => r.data) });
  const an = useQuery({ queryKey: ["inst-analytics", inst?.id, params], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/analytics`, { params }).then((r) => r.data) });
  const overview = useQuery({ queryKey: ["inst-overview", inst?.id], enabled: !!inst, queryFn: () => api.get(`/institutions/${inst.id}/overview`).then((r) => r.data) });
  const summary = useMutation({ mutationFn: () => api.post(`/institutions/${inst.id}/analytics/summary`, null, { params }).then((r) => r.data) });

  if (mine.isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;
  const a = an.data;
  const cohorts = [...new Set((a?.heatmap ?? []).map((h: any) => h.cohort_name))] as string[];
  const heatSkills = [...new Set((a?.heatmap ?? []).map((h: any) => h.skill_name))] as string[];
  const cell = (c: string, s: string) => a.heatmap.find((h: any) => h.cohort_name === c && h.skill_name === s);

  return (
    <div className="max-w-6xl space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">{inst.name}</h1>
        <div className="flex gap-2">
          <select className={inputCls} value={f.department_id} onChange={(e) => setF({ ...f, department_id: e.target.value })}>
            <option value="">All departments</option>{(structure.data?.departments ?? []).map((d: any) => <option key={d.id} value={d.id}>{d.name}</option>)}</select>
          <select className={inputCls} value={f.cohort_id} onChange={(e) => setF({ ...f, cohort_id: e.target.value })}>
            <option value="">All cohorts</option>{(structure.data?.cohorts ?? []).map((c: any) => <option key={c.id} value={c.id}>{c.name}</option>)}</select>
        </div>
      </div>
      {overview.data && (
        <div className="grid grid-cols-4 gap-3 text-sm" data-testid="overview-cards">
          {[["Active students", overview.data.active_students], ["Pending invitations", overview.data.pending_invitations],
            ["Profile completion", overview.data.profile_completion_pct == null ? "—" : `${overview.data.profile_completion_pct}%`],
            ["Assessment completed", overview.data.assessment_completed], ["Interview completed", overview.data.interview_completed],
            ["Applications", overview.data.applications], ["Shortlisted", overview.data.shortlisted], ["Offers", overview.data.offers]].map(([label, v]) => (
            <div key={label as string} className="border border-gray-200 rounded-md p-3 bg-white"><p className="text-xs text-gray-500">{label}</p><p className="text-xl font-semibold">{v as any}</p></div>))}
        </div>
      )}
      <ErrorBox error={an.error} onRetry={an.refetch} />
      {an.isLoading && <Loading label="Running analytics queries…" />}
      {a && (
        <>
          <div className="grid md:grid-cols-2 gap-4">
            <Card title="Role readiness (from stored matching_v1 scores)">
              <p className="text-sm">{a.readiness.students_ready} of {a.readiness.students_matched} matched students have required-skill fit ≥ {pct(a.readiness.readiness_threshold)}; average match {pct(a.readiness.avg_match_score, 1)}.</p>
            </Card>
            <Card title="Assessment performance">
              <p className="text-sm">{a.assessment_performance.attempts} scored attempts · average {pct(a.assessment_performance.avg_score, 1)} · range {pct(a.assessment_performance.min_score)}–{pct(a.assessment_performance.max_score)}</p>
            </Card>
          </div>
          <Card title="Application funnel">
            <div className="flex flex-wrap gap-4 text-sm">{a.funnel.map((s: any) => <span key={s.status}>{s.status.replaceAll("_", " ").toLowerCase()}: <b>{s.count}</b></span>)}</div>
          </Card>
          <Card title="Cohort skill heatmap (average verified level)">
            {cohorts.length === 0 ? <Empty>No verified skills among enrolled students in a cohort yet.</Empty> : (
              <Table head={["Cohort", ...heatSkills]}>
                {cohorts.map((c) => (
                  <tr key={c}><td className="py-1 pr-3 font-medium">{c}</td>
                    {heatSkills.map((s) => { const x = cell(c, s); return (
                      <td key={s} className="pr-2" style={{ background: x ? `rgba(17,24,39,${0.08 + x.average_level * 0.5})` : undefined, color: x && x.average_level > 0.6 ? "white" : undefined }}>
                        {x ? `${pct(x.average_level)} (n=${x.student_count})` : "—"}</td>); })}
                  </tr>))}
              </Table>)}
          </Card>
          <div className="grid md:grid-cols-2 gap-4">
            <Card title="Top gaps vs. industry demand">
              {a.strengths_and_gaps.gaps.length === 0 ? <Empty>No confirmed job requirements on the platform yet.</Empty> : (
                <Table head={["Skill", "Cohort avg", "Industry req.", "Gap"]}>{a.strengths_and_gaps.gaps.map((g: any) => (
                  <tr key={g.skill_id}><td className="py-1 pr-3">{g.skill_name}</td><td className="pr-3">{pct(g.cohort_avg_level)}</td><td className="pr-3">{pct(g.avg_required_level)}</td><td>{pct(g.gap)}</td></tr>))}</Table>)}
            </Card>
            <Card title="Top strengths">
              {a.strengths_and_gaps.strengths.length === 0 ? <Empty>No demonstrated in-demand skills yet.</Empty> : (
                <Table head={["Skill", "Cohort avg", "Industry req."]}>{a.strengths_and_gaps.strengths.map((g: any) => (
                  <tr key={g.skill_id}><td className="py-1 pr-3">{g.skill_name}</td><td className="pr-3">{pct(g.cohort_avg_level)}</td><td>{pct(g.avg_required_level)}</td></tr>))}</Table>)}
            </Card>
          </div>
          <Card title="Industry demand (confirmed requirements across all jobs)">
            <Table head={["Skill", "Jobs requiring", "Avg importance", "Avg required level"]}>{a.industry_demand.map((d: any) => (
              <tr key={d.skill_id}><td className="py-1 pr-3">{d.skill_name}</td><td className="pr-3">{d.demand_count}</td><td className="pr-3">{pct(d.avg_importance)}</td><td>{pct(d.avg_required_level)}</td></tr>))}</Table>
          </Card>
          <Card title="AI summary" actions={<Button variant="secondary" onClick={() => summary.mutate()} disabled={summary.isPending}>{summary.isPending ? "Summarizing…" : "Summarize"}</Button>}>
            {summary.data?.text ? <p className="text-sm">{summary.data.text} <span className="text-xs text-gray-400">({summary.data.generated_by})</span></p> : <Empty>Optional. Written by an LLM from the figures above; it never produces numbers.</Empty>}
            {summary.data?.error && <p className="text-xs text-red-600">{summary.data.error}</p>}
            <ErrorBox error={summary.error} />
          </Card>
        </>
      )}
      <Card title="Student roster">
        {roster.isLoading && <Loading />}
        {(roster.data ?? []).length === 0 && !roster.isLoading && <Empty>No enrolled students{f.cohort_id || f.department_id ? " for this filter" : ""}.</Empty>}
        {(roster.data ?? []).length > 0 && (
          <Table head={["Name", "Email", "Department", "Cohort", "Verified skills", "Avg level", "Applications"]}>{roster.data.map((s: any) => (
            <tr key={s.student_id}><td className="py-1 pr-3"><Link className="underline" to={`/institution/institutions/${inst.id}/students/${s.student_id}`}>{s.name}</Link></td><td className="pr-3 text-xs">{s.email}</td><td className="pr-3">{s.department ?? "—"}</td>
              <td className="pr-3">{s.cohort ?? "—"}</td><td className="pr-3">{s.verified_skills}</td><td className="pr-3">{pct(s.avg_level)}</td><td>{s.applications}</td></tr>))}</Table>)}
      </Card>
    </div>
  );
}
