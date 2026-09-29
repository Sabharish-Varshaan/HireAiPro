import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import {
  Badge,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  humanize,
} from "../../components/ui";
import { AssessmentRunner } from "../assessments/AssessmentRunner";
import { InterviewRunner } from "../interviews/InterviewRunner";
import { ProctoredGate } from "../proctoring/ProctoredGate";

/** The interview record is created the moment the proctored session becomes active; no extra click. */
function AutoStart({ onStart, pending }: { onStart: () => void; pending: boolean }) {
  const fired = useRef(false);
  useEffect(() => {
    if (!fired.current) {
      fired.current = true;
      onStart();
    }
  }, [onStart]);
  return <p className="text-sm text-gray-600">{pending ? "Starting your interview…" : "Starting…"}</p>;
}

export default function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const qc = useQueryClient();

  const app = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}`).then((r) => r.data),
  });
  const history = useQuery({
    queryKey: ["history", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}/history`).then((r) => r.data),
  });

  const a = app.data;
  const assessment = useQuery({
    queryKey: ["assessment-by-job", a?.job_id],
    enabled: !!a?.job_id,
    queryFn: () => api.get(`/assessments/by-job/${a.job_id}`).then((r) => r.data),
  });
  const interview = useQuery({
    queryKey: ["interview", applicationId],
    queryFn: () => api.get(`/interviews/by-application/${applicationId}`).then((r) => r.data),
  });
  const match = useQuery({
    queryKey: ["match", applicationId],
    retry: false,
    queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data),
  });
  const attemptQ = useQuery({
    queryKey: ["attempt-by-app", applicationId],
    queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`).then((r) => r.data),
  });

  const assessmentDone = ["SUBMITTED", "SCORED"].includes(attemptQ.data?.attempt?.status);
  const interviewDone = interview.data?.status === "COMPLETED";

  const prepare = useQuery({
    queryKey: ["interview-prepare", applicationId],
    enabled: !!a && ["ASSESSMENT_COMPLETED", "INTERVIEW_PENDING"].includes(a.status) && !interview.data,
    staleTime: Infinity,
    queryFn: () => api.post("/interviews/prepare", { application_id: applicationId }).then((r) => r.data),
  });
  const readiness = useQuery({
    queryKey: ["interview-readiness", applicationId],
    enabled: prepare.isSuccess && !prepare.data?.ready,
    refetchInterval: 2000,
    queryFn: () => api.get(`/interviews/readiness/${applicationId}`).then((r) => r.data),
  });
  const poolReady = !!(prepare.data?.ready || readiness.data?.ready);

  const refreshAll = () =>
    ["application", "history", "interview", "match", "attempt-by-app"].forEach((k) =>
      qc.invalidateQueries({ queryKey: [k] })
    );

  const startInterview = useMutation({
    mutationFn: () => api.post("/interviews/start", { application_id: applicationId }),
    onSuccess: refreshAll,
  });

  if (app.isLoading) return <Loading />;
  if (app.error) return <ErrorBox error={app.error} onRetry={app.refetch} />;

  const interviewAllowed =
    ["ASSESSMENT_COMPLETED", "INTERVIEW_PENDING"].includes(a.status) || interview.data;

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        back={{ label: "My applications", href: "/student/applications" }}
        title={a.job_title}
        description={a.organization_name}
        actions={<Badge>{a.status}</Badge>}
      />

      {/* Visual Application Timeline */}
      <Card title="Application Journey" description="Chronological record of status changes and evaluation steps.">
        {(history.data ?? []).length === 0 ? (
          <Empty>No history available yet.</Empty>
        ) : (
          <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-200">
            {(history.data ?? []).map((h: any, i: number) => (
              <div key={i} className="relative flex items-start gap-3 text-xs">
                <div className="absolute -left-6 mt-1 w-3 h-3 rounded-full bg-blue-600 ring-4 ring-white" />
                <div className="flex-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900">{humanize(h.to)}</span>
                    <span className="text-gray-400 font-mono text-[11px]">
                      {new Date(h.at).toLocaleDateString()} {new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                  </div>
                  {h.note && <p className="text-gray-600 text-xs italic">“{h.note}”</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Technical Assessment Card */}
      <Card
        title="Step 1: Technical Assessment"
        description="MCQ, technical written, and coding evaluations."
        actions={attemptQ.data?.attempt ? <Badge>{attemptQ.data.attempt.status}</Badge> : null}
      >
        {!assessment.data ? (
          <Empty>No technical assessment has been published for this role yet.</Empty>
        ) : attemptQ.isLoading ? (
          <Loading label="Checking assessment status…" />
        ) : assessmentDone ? (
          <AssessmentRunner
            assessmentId={assessment.data.id}
            applicationId={applicationId!}
            onSubmitted={refreshAll}
          />
        ) : (
          <ProctoredGate applicationId={applicationId!} kind="ASSESSMENT">
            {(complete) => (
              <AssessmentRunner
                assessmentId={assessment.data.id}
                applicationId={applicationId!}
                onSubmitted={() => {
                  void complete();
                  refreshAll();
                }}
              />
            )}
          </ProctoredGate>
        )}
      </Card>

      {/* AI Conversational Interview Card */}
      <Card
        title="Step 2: AI Conversational Interview"
        description="Structured, audio-enabled conversational interview assessing competencies and problem solving."
        actions={interview.data ? <Badge>{interview.data.status}</Badge> : null}
      >
        {!interviewAllowed && (
          <Empty>The interview step unlocks automatically after your technical assessment is submitted.</Empty>
        )}
        {interviewAllowed &&
          (interview.isLoading ? (
            <Loading label="Loading interview session…" />
          ) : interviewDone ? (
            <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-lg text-xs text-emerald-900">
              ✓ <strong>Interview Completed:</strong> Your responses have been transcribed and submitted for recruiter evaluation.
            </div>
          ) : (
            <ProctoredGate
              applicationId={applicationId!}
              kind="INTERVIEW"
              preparing={
                interview.data
                  ? undefined
                  : { ready: poolReady, label: "Preparing your interview questions pool…" }
              }
            >
              {(complete, stream) =>
                !interview.data ? (
                  <AutoStart onStart={() => startInterview.mutate()} pending={startInterview.isPending} />
                ) : (
                  <InterviewRunner
                    interviewId={interview.data.id}
                    mediaStream={stream}
                    onCompleted={() => void complete()}
                  />
                )
              }
            </ProctoredGate>
          ))}
        <ErrorBox error={startInterview.error} />
      </Card>

      {/* Strengths & Development Roadmap */}
      <Card
        title="Step 3: Verified Strengths & Learning Roadmap"
        description="Personalized competency breakdown generated from your assessment performance."
      >
        {!match.data ? (
          <Empty>Detailed feedback and learning roadmap will appear here once your interview is complete.</Empty>
        ) : (
          <div className="space-y-4 text-sm">
            {[
              ["Demonstrated Strengths", match.data.strengths, "green"],
              ["Competencies to Develop", match.data.skills_to_develop, "amber"],
              ["Not Yet Demonstrated", match.data.missing_skills, "red"],
            ].map(([title, items, tone]: any) => (
              <div key={title} className="space-y-1.5">
                <p className="text-xs font-semibold text-gray-700">{title}</p>
                <div className="flex flex-wrap gap-1.5">
                  {(items ?? []).map((name: string) => (
                    <Badge key={name} tone={tone}>
                      {name}
                    </Badge>
                  ))}
                  {(items ?? []).length === 0 && <span className="text-xs text-gray-400">None identified</span>}
                </div>
              </div>
            ))}
            <div className="pt-2">
              <Link
                className="inline-flex items-center text-xs font-semibold px-3 py-2 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 transition"
                to={`/student/career/${a.job_id}`}
              >
                Build My Learning Roadmap →
              </Link>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}
