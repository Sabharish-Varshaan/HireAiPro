import { useMutation, useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorBox, Loading } from "../../components/ui";
import { STAGE_BLURB, fmtScore, type JourneyStage } from "../../lib/pipeline";
import { AssessmentRunner } from "../assessments/AssessmentRunner";
import { InterviewRunner } from "../interviews/InterviewRunner";
import { ProctoredGate } from "../proctoring/ProctoredGate";

/** ✓ Applied → ✓ done stages → current stage → ○ upcoming → Final review. Only the stages this job actually uses are listed. */
export function JourneyStrip({ stages, applied, decided }: { stages: JourneyStage[]; applied?: string; decided: boolean }) {
  const items: { key: string; label: string; state: "done" | "current" | "todo" | "skipped" }[] = [
    { key: "applied", label: "Applied", state: "done" },
    ...stages.map((s) => ({
      key: s.stage_id,
      label: s.label,
      state: (s.status === "COMPLETED" ? "done" : s.status === "SKIPPED" ? "skipped" : s.status === "LOCKED" ? "todo" : "current") as "done" | "current" | "todo" | "skipped",
    })),
    { key: "final", label: "Final Review", state: decided ? "done" : "todo" },
  ];
  return (
    <ol className="space-y-2" aria-label="Your hiring journey" data-testid="hiring-journey">
      {items.map((it) => (
        <li key={it.key} className="flex items-center gap-3 text-sm" data-state={it.state}>
          <span
            aria-hidden="true"
            className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
              it.state === "done" ? "bg-emerald-600 text-white" : it.state === "current" ? "bg-blue-600 text-white" : it.state === "skipped" ? "bg-gray-300 text-white" : "border border-gray-300 text-gray-400"
            }`}
          >
            {it.state === "done" ? "✓" : it.state === "current" ? "→" : it.state === "skipped" ? "–" : "○"}
          </span>
          <span className={it.state === "todo" ? "text-gray-500" : "font-medium text-gray-900"}>{it.label}</span>
          {it.state === "current" && <span className="text-xs font-medium text-blue-700">Your turn</span>}
          {it.key === "applied" && applied && <span className="text-xs text-gray-400">{applied}</span>}
        </li>
      ))}
    </ol>
  );
}

function CompletedNote({ stage, interview }: { stage: JourneyStage; interview?: boolean }) {
  const r = stage.round;
  return (
    <div className="space-y-3">
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 p-3 text-xs text-emerald-900" data-testid={`stage-done-${stage.stage_type}`}>
        ✓ <strong>{stage.label} completed</strong>
        {stage.completed_at ? ` on ${new Date(stage.completed_at).toLocaleDateString()}` : ""}.{" "}
        {interview ? "Your answers were shared with the hiring team." : "Your responses were saved and scored. Results are shared with the recruiter."}
      </div>
      {r && (
        <dl className="grid grid-cols-1 gap-3 rounded-lg border border-gray-200 bg-white p-3 text-sm sm:grid-cols-4" data-testid={`round-result-${stage.stage_type}`}>
          {r.decision === "EVALUATION_PENDING" ? (
            <div className="sm:col-span-4"><dt className="text-xs text-gray-500">Result</dt><dd className="font-medium text-gray-900">We are still evaluating this round.</dd></div>
          ) : (
            <>
              <div><dt className="text-xs text-gray-500">Score</dt><dd className="text-lg font-semibold text-gray-900">{fmtScore(r.score)}</dd></div>
              <div><dt className="text-xs text-gray-500">Qualification requirement</dt><dd className="text-lg font-semibold text-gray-900">{fmtScore(r.threshold)}</dd></div>
              <div><dt className="text-xs text-gray-500">Result</dt><dd className={`font-medium ${r.decision === "QUALIFIED" ? "text-emerald-700" : "text-gray-900"}`}>{r.result_label}</dd></div>
              {r.next && <div><dt className="text-xs text-gray-500">Next</dt><dd className="font-medium text-gray-900">{r.next}</dd></div>}
            </>
          )}
        </dl>
      )}
    </div>
  );
}

function AssessmentStage({ applicationId, stage, onChange }: { applicationId: string; stage: JourneyStage; onChange: () => void }) {
  if (stage.status === "COMPLETED" || stage.status === "SKIPPED") return <CompletedNote stage={stage} />;
  const runner = (complete?: () => Promise<void>) => (
    <AssessmentRunner
      assessmentId={stage.assessment_id!}
      applicationId={applicationId}
      onSubmitted={() => {
        void complete?.();
        onChange();
      }}
    />
  );
  return stage.proctored === false ? runner() : (
    <ProctoredGate applicationId={applicationId} kind="ASSESSMENT">{(complete) => runner(complete)}</ProctoredGate>
  );
}

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

function InterviewStage({ applicationId, stage, onChange }: { applicationId: string; stage: JourneyStage; onChange: () => void }) {
  const done = stage.status === "COMPLETED" || stage.status === "SKIPPED";
  const interview = useQuery({
    queryKey: ["interview", applicationId, stage.stage_type],
    queryFn: () => api.get(`/interviews/by-application/${applicationId}`, { params: { stage_type: stage.stage_type } }).then((r) => r.data),
  });
  const prepare = useQuery({
    queryKey: ["interview-prepare", applicationId, stage.stage_type],
    enabled: !done && !interview.isLoading && !interview.data,
    staleTime: Infinity,
    queryFn: () => api.post("/interviews/prepare", { application_id: applicationId, stage_type: stage.stage_type }).then((r) => r.data),
  });
  const readiness = useQuery({
    queryKey: ["interview-readiness", applicationId, stage.stage_type],
    enabled: prepare.isSuccess && !prepare.data?.ready,
    refetchInterval: 2000,
    queryFn: () => api.get(`/interviews/readiness/${applicationId}`, { params: { stage_type: stage.stage_type } }).then((r) => r.data),
  });
  const ready = !!(prepare.data?.ready || readiness.data?.ready);
  const start = useMutation({
    mutationFn: () => api.post("/interviews/start", { application_id: applicationId, stage_type: stage.stage_type }),
    onSuccess: onChange,
  });
  if (done) return <CompletedNote stage={stage} interview />;
  if (interview.isLoading) return <Loading label="Loading your interview…" />;
  const label = "Preparing your interview questions…";
  const body = (complete?: () => Promise<void>, stream?: MediaStream | null) =>
    !interview.data ? (
      <AutoStart onStart={() => start.mutate()} pending={start.isPending} />
    ) : (
      <InterviewRunner
        interviewId={interview.data.id}
        mediaStream={stream}
        stageType={stage.stage_type}
        total={interview.data.question_budget}
        minQuestions={interview.data.min_questions}
        onCompleted={() => {
          void complete?.();
          onChange();
        }}
      />
    );
  return (
    <>
      {stage.proctored === false ? (
        !interview.data && !ready ? <Loading label={label} /> : body()
      ) : (
        <ProctoredGate applicationId={applicationId} kind="INTERVIEW" preparing={interview.data ? undefined : { ready, label }}>
          {(complete, stream) => body(complete, stream)}
        </ProctoredGate>
      )}
      <ErrorBox error={start.error} />
    </>
  );
}

/** One card per stage of this job's hiring process, in order. Locked stages say what unlocks them; nothing is startable out of order. */
export function StageCards({ applicationId, stages, onChange }: { applicationId: string; stages: JourneyStage[]; onChange: () => void }) {
  return (
    <>
      {stages.map((s, i) => (
        <Card
          key={s.stage_id}
          title={`Step ${i + 1}: ${s.label}`}
          description={STAGE_BLURB[s.stage_type]}
          actions={<Badge>{s.status}</Badge>}
        >
          {s.status === "LOCKED" ? (
            <Empty>
              {i === 0
                ? "This step is not open yet."
                : stages[i - 1].status === "COMPLETED" && stages[i - 1].round && stages[i - 1].round!.decision !== "QUALIFIED"
                ? "This step is not open. The hiring team reviews your result from the previous step."
                : `This step opens after you finish ${stages[i - 1].label}.`}
            </Empty>
          ) : s.kind === "assessment" ? (
            s.assessment_id ? <AssessmentStage applicationId={applicationId} stage={s} onChange={onChange} /> : <Empty>The questions for this step are not published yet.</Empty>
          ) : (
            <InterviewStage applicationId={applicationId} stage={s} onChange={onChange} />
          )}
        </Card>
      ))}
    </>
  );
}
