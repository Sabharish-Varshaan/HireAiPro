import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorBox, Loading, Table, pct } from "../../components/ui";
import { StageTimeline } from "../company/CandidateStages";
import { ProctoringPanel } from "../proctoring/ProctoringPanel";

function ApplicationReview({ app }: { app: any }) {
  const pipeline = useQuery({ queryKey: ["inst-pipeline", app.id], retry: false,
    queryFn: () => api.get(`/hiring-pipeline/applications/${app.id}`).then((r) => r.data) });
  const match = useQuery({ queryKey: ["inst-match", app.id], retry: false,
    queryFn: () => api.get(`/matching/applications/${app.id}`).then((r) => r.data) });
  const stages: any[] = pipeline.data?.stages ?? [];
  return (
    <Card title={`${app.job_title} · ${app.organization_name}`} actions={<Badge>{app.status}</Badge>}>
      <div className="text-sm space-y-3 mb-3">
        <div>
          <p className="text-xs font-medium mb-1.5">Hiring stages</p>
          {pipeline.isLoading ? <Loading /> : stages.length === 0 ? <p className="text-xs text-gray-500">No stages yet.</p> : (
            <>
              <StageTimeline stages={stages} applicationStatus={app.status} />
              <ul className="mt-2 grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-1 text-xs text-gray-700" data-testid="officer-stage-status">
                {stages.map((s) => (
                  <li key={s.stage_id} className="flex items-center justify-between gap-2">
                    <span>{s.label}</span>
                    <span className="font-medium">{s.status === "COMPLETED" ? "Completed" : s.status === "IN_PROGRESS" ? "In progress" : s.status === "AVAILABLE" ? "Pending" : s.status === "SKIPPED" ? "Skipped" : "Locked"}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <p>Match: {match.data?.match_score != null ? pct(match.data.match_score) : "not computed"}</p>
      </div>
      <p className="text-xs font-medium mb-1">Proctoring</p>
      <ProctoringPanel applicationId={app.id} />
    </Card>
  );
}

export default function InstitutionStudentPage() {
  const { institutionId, studentId } = useParams();
  const q = useQuery({ queryKey: ["inst-student", studentId],
    queryFn: () => api.get(`/institutions/${institutionId}/students/${studentId}/applications`).then((r) => r.data) });
  const skills = useQuery({ queryKey: ["inst-skills", studentId], retry: false,
    queryFn: () => api.get(`/evidence/students/${studentId}/skills`).then((r) => r.data) });
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  return (
    <div className="max-w-4xl space-y-4">
      <Link to="/institution/students" className="text-xs text-gray-500 underline">← Students</Link>
      <h1 className="text-lg font-semibold">{q.data.name}</h1>
      <Card title="Verified skills">
        {skills.isLoading && <Loading />}
        {(skills.data ?? []).length === 0 && !skills.isLoading && <Empty>No verified skill evidence yet.</Empty>}
        {(skills.data ?? []).length > 0 && (
          <Table head={["Skill", "Level", "Confidence", "Evidence"]}>{skills.data.map((k: any) => (
            <tr key={k.skill_id}><td className="py-1 pr-3">{k.skill_name}</td><td className="pr-3">{pct(k.estimated_level)}</td>
              <td className="pr-3">{pct(k.confidence)}</td><td>{k.evidence_count}</td></tr>))}</Table>)}
      </Card>
      {q.data.applications.length === 0 ? <Empty>No applications yet.</Empty> :
        q.data.applications.map((a: any) => <ApplicationReview key={a.id} app={a} />)}
    </div>
  );
}
