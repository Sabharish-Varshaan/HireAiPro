import { Link } from "react-router-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import {
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  MetricCard,
  PageHeader,
  Table,
  inputCls,
  pct,
} from "../../components/ui";

export default function InstitutionDashboard() {
  const mine = useQuery({
    queryKey: ["my-institutions"],
    queryFn: () => api.get("/institutions/mine").then((r) => r.data),
  });
  const inst = mine.data?.[0];
  const [f, setF] = useState({ department_id: "", cohort_id: "" });
  const params = Object.fromEntries(Object.entries(f).filter(([, v]) => v));

  const structure = useQuery({
    queryKey: ["structure", inst?.id],
    enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/structure`).then((r) => r.data),
  });
  const roster = useQuery({
    queryKey: ["roster", inst?.id, params],
    enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/roster`, { params }).then((r) => r.data),
  });
  const an = useQuery({
    queryKey: ["inst-analytics", inst?.id, params],
    enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/analytics`, { params }).then((r) => r.data),
  });
  const overview = useQuery({
    queryKey: ["inst-overview", inst?.id],
    enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/overview`).then((r) => r.data),
  });
  const summary = useMutation({
    mutationFn: () => api.post(`/institutions/${inst.id}/analytics/summary`, null, { params }).then((r) => r.data),
  });

  if (mine.isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;

  const a = an.data;
  const cohorts = [...new Set((a?.heatmap ?? []).map((h: any) => h.cohort_name))] as string[];
  const heatSkills = [...new Set((a?.heatmap ?? []).map((h: any) => h.skill_name))] as string[];
  const cell = (c: string, s: string) => a.heatmap.find((h: any) => h.cohort_name === c && h.skill_name === s);

  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={inst.name}
        description="Campus placement performance, cohort readiness, and company hiring analytics."
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <select
              className={`${inputCls} w-44`}
              value={f.department_id}
              onChange={(e) => setF({ ...f, department_id: e.target.value })}
            >
              <option value="">All departments</option>
              {(structure.data?.departments ?? []).map((d: any) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
            <select
              className={`${inputCls} w-40`}
              value={f.cohort_id}
              onChange={(e) => setF({ ...f, cohort_id: e.target.value })}
            >
              <option value="">All cohorts</option>
              {(structure.data?.cohorts ?? []).map((c: any) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        }
      />

      {/* Priority Metrics Cards Grid */}
      {overview.data && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-sm" data-testid="overview-cards">
            {[
              ["Active students", overview.data.active_students, "success"],
              ["Applications", overview.data.applications, "info"],
              ["Shortlisted", overview.data.shortlisted, "default"],
              ["Offers", overview.data.offers, "success"],
              ["Pending invitations", overview.data.pending_invitations, "warning"],
              [
                "Profile completion",
                overview.data.profile_completion_pct == null
                  ? "—"
                  : `${overview.data.profile_completion_pct}%`,
                "default",
              ],
              ["Assessment completed", overview.data.assessment_completed, "default"],
              ["Interview completed", overview.data.interview_completed, "default"],
            ].map(([label, v, tone]) => (
              <MetricCard
                key={label as string}
                label={label as string}
                value={v as any}
                tone={tone as any}
              />
            ))}
          </div>
        </div>
      )}

      <ErrorBox error={an.error} onRetry={an.refetch} />
      {an.isLoading && <Loading label="Running cohort analytics queries…" />}

      {a && (
        <>
          {/* Readiness and Assessment Performance */}
          <div className="grid md:grid-cols-2 gap-4">
            <Card
              title="Role Readiness & Matching"
              description="Student readiness computed against live industry job requirements."
            >
              <div className="p-3 bg-blue-50/60 border border-blue-200 rounded-lg text-sm text-blue-950 space-y-1">
                <p className="font-semibold text-base">
                  {a.readiness.students_ready} of {a.readiness.students_matched} matched students
                </p>
                <p className="text-xs text-blue-800">
                  Meet or exceed the minimum requirement fit threshold (≥ {pct(a.readiness.readiness_threshold)}).
                  Average candidate match: <b>{pct(a.readiness.avg_match_score, 1)}</b>.
                </p>
              </div>
            </Card>

            <Card
              title="Assessment Performance"
              description="Cohort technical test scores across all campus drives."
            >
              <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg text-sm text-gray-800 space-y-1">
                <p className="font-semibold text-base">{a.assessment_performance.attempts} scored attempts</p>
                <p className="text-xs text-gray-600">
                  Average score: <b>{pct(a.assessment_performance.avg_score, 1)}</b> · Score range:{" "}
                  {pct(a.assessment_performance.min_score)} – {pct(a.assessment_performance.max_score)}
                </p>
              </div>
            </Card>
          </div>

          {/* Application Funnel */}
          <Card
            title="Placement Funnel Stages"
            description="Overall student progression across open applications."
          >
            <div className="flex flex-wrap gap-2.5">
              {a.funnel.map((s: any) => (
                <div
                  key={s.status}
                  className="px-3.5 py-2 rounded-xl bg-gray-50 border border-gray-200 text-xs flex items-center gap-2"
                >
                  <span className="capitalize text-gray-700">{s.status.replaceAll("_", " ").toLowerCase()}:</span>
                  <span className="font-bold text-gray-900 text-sm">{s.count}</span>
                </div>
              ))}
            </div>
          </Card>

          {/* Skill Heatmap */}
          <Card
            title="Cohort Skill Heatmap"
            description="Average demonstrated competency score per cohort based on verified evaluations."
          >
            {cohorts.length === 0 ? (
              <Empty>No verified skills among enrolled students in this cohort yet.</Empty>
            ) : (
              <Table head={["Cohort", ...heatSkills]}>
                {cohorts.map((c) => (
                  <tr key={c} className="hover:bg-gray-50/50">
                    <td className="py-2 pr-3 font-semibold text-gray-900 text-xs">{c}</td>
                    {heatSkills.map((s) => {
                      const x = cell(c, s);
                      return (
                        <td
                          key={s}
                          className="pr-2 text-xs"
                          style={{
                            background: x ? `rgba(29, 78, 216, ${0.08 + x.average_level * 0.45})` : undefined,
                            color: x && x.average_level > 0.6 ? "#1e3a8a" : undefined,
                          }}
                        >
                          {x ? (
                            <span className="font-medium">
                              {pct(x.average_level)}{" "}
                              <span className="text-[10px] text-gray-500 font-normal">(n={x.student_count})</span>
                            </span>
                          ) : (
                            "—"
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </Table>
            )}
          </Card>

          {/* Top Gaps vs Strengths */}
          <div className="grid md:grid-cols-2 gap-4">
            <Card
              title="Skill Gaps vs. Industry Demand"
              description="Where cohort demonstrated levels fall below employer requirements."
            >
              {a.strengths_and_gaps.gaps.length === 0 ? (
                <Empty>No confirmed job requirements or gaps detected on the platform yet.</Empty>
              ) : (
                <Table head={["Skill", "Cohort Avg", "Industry Req.", "Gap"]}>
                  {a.strengths_and_gaps.gaps.map((g: any) => (
                    <tr key={g.skill_id} className="hover:bg-gray-50/50">
                      <td className="py-2 pr-3 font-medium text-gray-900 text-xs">{g.skill_name}</td>
                      <td className="pr-3 text-xs">{pct(g.cohort_avg_level)}</td>
                      <td className="pr-3 text-xs">{pct(g.avg_required_level)}</td>
                      <td className="text-xs font-semibold text-red-600">-{pct(g.gap)}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>

            <Card
              title="Top Demonstrated Strengths"
              description="Areas where students exceed or meet market hiring expectations."
            >
              {a.strengths_and_gaps.strengths.length === 0 ? (
                <Empty>No demonstrated in-demand skills verified yet.</Empty>
              ) : (
                <Table head={["Skill", "Cohort Avg", "Industry Req."]}>
                  {a.strengths_and_gaps.strengths.map((g: any) => (
                    <tr key={g.skill_id} className="hover:bg-gray-50/50">
                      <td className="py-2 pr-3 font-medium text-gray-900 text-xs">{g.skill_name}</td>
                      <td className="pr-3 text-xs font-semibold text-emerald-700">{pct(g.cohort_avg_level)}</td>
                      <td className="text-xs text-gray-600">{pct(g.avg_required_level)}</td>
                    </tr>
                  ))}
                </Table>
              )}
            </Card>
          </div>

          {/* Industry Demand */}
          <Card
            title="Industry Competency Demand"
            description="Most frequently requested skills and required proficiency across all employer roles."
          >
            <Table head={["Skill", "Active Roles Requiring", "Average Importance", "Average Required Level"]}>
              {a.industry_demand.map((d: any) => (
                <tr key={d.skill_id} className="hover:bg-gray-50/50">
                  <td className="py-2 pr-3 font-medium text-gray-900 text-xs">{d.skill_name}</td>
                  <td className="pr-3 text-xs font-semibold">{d.demand_count} roles</td>
                  <td className="pr-3 text-xs">{pct(d.avg_importance)}</td>
                  <td className="text-xs font-semibold text-blue-700">{pct(d.avg_required_level)}</td>
                </tr>
              ))}
            </Table>
          </Card>

          {/* AI Executive Summary */}
          <Card
            title="Executive Placement Summary"
            description="Synthesis generated from the cohort figures above."
            actions={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => summary.mutate()}
                disabled={summary.isPending}
              >
                {summary.isPending ? "Generating…" : "Generate AI Summary"}
              </Button>
            }
          >
            {summary.data?.text ? (
              <p className="text-xs text-gray-800 leading-relaxed bg-gray-50 p-3.5 rounded-lg border border-gray-100">
                {summary.data.text}
              </p>
            ) : (
              <Empty>Click Generate AI Summary to synthesize key placement highlights and action items.</Empty>
            )}
            {summary.data?.error && <p className="text-xs text-red-600 mt-2">{summary.data.error}</p>}
            <ErrorBox error={summary.error} />
          </Card>
        </>
      )}

      {/* Student Roster */}
      <Card title="Enrolled Student Roster" description="Individual student tracking and verified performance.">
        {roster.isLoading && <Loading />}
        {(roster.data ?? []).length === 0 && !roster.isLoading && (
          <Empty>No enrolled students{f.cohort_id || f.department_id ? " matching this filter" : ""}.</Empty>
        )}
        {(roster.data ?? []).length > 0 && (
          <Table head={["Student Name", "Email", "Department", "Cohort", "Verified Skills", "Avg Level", "Applications"]}>
            {roster.data.map((s: any) => (
              <tr key={s.student_id} className="hover:bg-gray-50/50">
                <td className="py-2.5 pr-3 font-medium text-gray-900 text-xs">
                  <Link
                    className="text-blue-700 hover:text-blue-900 underline"
                    to={`/institution/institutions/${inst.id}/students/${s.student_id}`}
                  >
                    {s.name}
                  </Link>
                </td>
                <td className="pr-3 text-xs text-gray-500 font-mono">{s.email}</td>
                <td className="pr-3 text-xs text-gray-700">{s.department ?? "—"}</td>
                <td className="pr-3 text-xs text-gray-700">{s.cohort ?? "—"}</td>
                <td className="pr-3 text-xs font-semibold">{s.verified_skills}</td>
                <td className="pr-3 text-xs font-semibold text-blue-700">{pct(s.avg_level)}</td>
                <td className="text-xs font-medium text-gray-900">{s.applications}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
