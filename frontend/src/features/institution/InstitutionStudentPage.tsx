import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorBox, Loading, Table, pct } from "../../components/ui";
import { ProctoringPanel } from "../proctoring/ProctoringPanel";

function ApplicationReview({ app }: { app: any }) {
  const attempt = useQuery({ queryKey: ["inst-attempt", app.id], retry: false,
    queryFn: () => api.get(`/assessments/attempts/by-application/${app.id}`).then((r) => r.data) });
  const interview = useQuery({ queryKey: ["inst-interview", app.id], retry: false,
    queryFn: () => api.get(`/interviews/by-application/${app.id}`).then((r) => r.data) });
  const match = useQuery({ queryKey: ["inst-match", app.id], retry: false,
    queryFn: () => api.get(`/matching/applications/${app.id}`).then((r) => r.data) });
  return (
    <Card title={`${app.job_title} · ${app.organization_name}`} actions={<Badge>{app.status}</Badge>}>
      <div className="text-sm space-y-1 mb-3">
        <p>Assessment: {attempt.data?.attempt ? <>{attempt.data.attempt.status} · score {pct(attempt.data.attempt.total_score)}</> : "not started"}</p>
        <p>Interview: {interview.data ? interview.data.status : "not started"}</p>
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
      <Card title="Verified skills (SkillEstimator)">
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
