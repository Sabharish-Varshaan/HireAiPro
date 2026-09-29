import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading } from "../../components/ui";
import { AssessmentRunner } from "../assessments/AssessmentRunner";
import { InterviewRunner } from "../interviews/InterviewRunner";
import { ProctoredGate } from "../proctoring/ProctoredGate";

export default function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const qc = useQueryClient();
  const app = useQuery({ queryKey: ["application", applicationId], queryFn: () => api.get(`/applications/${applicationId}`).then((r) => r.data) });
  const history = useQuery({ queryKey: ["history", applicationId], queryFn: () => api.get(`/applications/${applicationId}/history`).then((r) => r.data) });
  const a = app.data;
  const assessment = useQuery({ queryKey: ["assessment-by-job", a?.job_id], enabled: !!a?.job_id,
    queryFn: () => api.get(`/assessments/by-job/${a.job_id}`).then((r) => r.data) });
  const interview = useQuery({ queryKey: ["interview", applicationId], queryFn: () => api.get(`/interviews/by-application/${applicationId}`).then((r) => r.data) });
  const match = useQuery({ queryKey: ["match", applicationId], retry: false, queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data) });
  const attemptQ = useQuery({ queryKey: ["attempt-by-app", applicationId],
    queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`).then((r) => r.data) });
  const assessmentDone = ["SUBMITTED", "SCORED"].includes(attemptQ.data?.attempt?.status);
  const interviewDone = interview.data?.status === "COMPLETED";
  const refreshAll = () => ["application", "history", "interview", "match", "attempt-by-app"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
  const startInterview = useMutation({ mutationFn: () => api.post("/interviews/start", { application_id: applicationId }), onSuccess: refreshAll });

  if (app.isLoading) return <Loading />;
  if (app.error) return <ErrorBox error={app.error} onRetry={app.refetch} />;
  const interviewAllowed = ["ASSESSMENT_COMPLETED", "INTERVIEW_PENDING"].includes(a.status) || interview.data;

  return (
    <div className="max-w-4xl space-y-5">
      <div>
        <Link to="/student/applications" className="text-xs text-gray-500 underline">← Applications</Link>
        <div className="flex items-center gap-3"><h1 className="text-lg font-semibold">{a.job_title}</h1><Badge>{a.status}</Badge></div>
        <p className="text-xs text-gray-500">{a.organization_name}</p>
      </div>

      <Card title="Progress">
        <ol className="text-xs text-gray-600 space-y-1">
          {(history.data ?? []).map((h: any, i: number) => (
            <li key={i}>{new Date(h.at).toLocaleString()} — <b>{h.to.replaceAll("_", " ")}</b>{h.note ? ` · ${h.note}` : ""}</li>
          ))}
        </ol>
      </Card>

      <Card title="Assessment">
        {!assessment.data ? <Empty>No published assessment for this job.</Empty> :
          assessmentDone ? <AssessmentRunner assessmentId={assessment.data.id} applicationId={applicationId!} onSubmitted={refreshAll} /> :
          <ProctoredGate applicationId={applicationId!} kind="ASSESSMENT">
            {(complete) => <AssessmentRunner assessmentId={assessment.data.id} applicationId={applicationId!}
              onSubmitted={() => { void complete(); refreshAll(); }} />}
          </ProctoredGate>}
      </Card>

      <Card title="Interview" actions={interview.data ? <Badge>{interview.data.status}</Badge> : null}>
        {!interviewAllowed && <Empty>Available after you submit the assessment.</Empty>}
        {interviewAllowed && (interviewDone ? <p className="text-sm font-medium">Interview completed</p> : (
          <ProctoredGate applicationId={applicationId!} kind="INTERVIEW">
            {(complete, stream) => !interview.data ? (
              <Button onClick={() => startInterview.mutate()} disabled={startInterview.isPending}>Start interview</Button>
            ) : <InterviewRunner interviewId={interview.data.id} mediaStream={stream} onCompleted={() => void complete()} />}
          </ProctoredGate>
        ))}
        <ErrorBox error={startInterview.error} />
      </Card>

      <Card title="Your strengths and skills to develop">
        {!match.data ? <Empty>Available after your interview.</Empty> : (
          <div className="space-y-2 text-sm">
            {[["Strengths", match.data.strengths, "green"], ["Skills to develop", match.data.skills_to_develop, "amber"],
              ["Not yet demonstrated", match.data.missing_skills, "red"]].map(([t, items, tone]: any) => (
              <div key={t}><p className="text-xs font-medium">{t}</p>
                <div className="flex flex-wrap gap-1">{(items ?? []).map((name: string) => <Badge key={name} tone={tone}>{name}</Badge>)}
                  {(items ?? []).length === 0 && <span className="text-xs text-gray-400">none</span>}</div></div>
            ))}
            <Link className="underline text-sm" to={`/student/career/${a.job_id}`}>Build my learning roadmap →</Link>
          </div>
        )}
      </Card>
    </div>
  );
}
