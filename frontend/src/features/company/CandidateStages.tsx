import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, humanize, pct, questionTypeLabel } from "../../components/ui";
import { COMPONENT_LABEL, DECISION_LABEL, HR_CATEGORY_LABEL, fmtScore, type JourneyStage, type RoundView } from "../../lib/pipeline";

const LAYER_LABEL: Record<number, string> = { 1: "Core concept", 2: "How and why", 3: "Applied scenario", 4: "Edge case", 5: "Trade-off" };
const dot = (s: string) =>
  s === "COMPLETED" ? "bg-emerald-600 text-white" : s === "IN_PROGRESS" || s === "AVAILABLE" ? "bg-blue-600 text-white" : s === "SKIPPED" ? "bg-gray-300 text-white" : "border border-gray-300 text-gray-400";
const mark = (s: string) => (s === "COMPLETED" ? "✓" : s === "IN_PROGRESS" ? "…" : s === "AVAILABLE" ? "→" : s === "SKIPPED" ? "–" : "○");

/** Applied → each enabled stage → Decision. Shared by the company candidate page; the placement officer sees the same shape without results. */
export function StageTimeline({ stages, applicationStatus }: { stages: JourneyStage[]; applicationStatus: string }) {
  const decided = ["SHORTLISTED", "OFFER", "REJECTED"].includes(applicationStatus);
  const items = [
    { key: "applied", label: "Applied", status: "COMPLETED" },
    ...stages.map((s) => ({ key: s.stage_id, label: s.label, full: s.label, status: s.status })),
    { key: "decision", label: decided ? humanize(applicationStatus) : "Decision", status: decided ? "COMPLETED" : "LOCKED" },
  ];
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2" aria-label="Hiring stages" data-testid="stage-timeline">
      {items.map((it: any, i) => (
        <li key={it.key} className="flex items-center gap-1" data-status={it.status}>
          {i > 0 && <span aria-hidden="true" className="mx-1 h-px w-5 bg-gray-300" />}
          <span aria-hidden="true" className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${dot(it.status)}`}>{mark(it.status)}</span>
          <span className={`text-xs ${it.status === "LOCKED" ? "text-gray-500" : "font-semibold text-gray-900"}`} title={`${it.full ?? it.label}: ${humanize(it.status)}`}>
            {it.label}
          </span>
        </li>
      ))}
    </ol>
  );
}

function AssessmentResult({ applicationId, stage }: { applicationId: string; stage: JourneyStage }) {
  const q = useQuery({
    queryKey: ["cand-attempt", applicationId, stage.assessment_id],
    enabled: !!stage.assessment_id && stage.status !== "LOCKED" && stage.status !== "AVAILABLE",
    queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`, { params: { assessment_id: stage.assessment_id } }).then((r) => r.data),
  });
  const r = stage.result;
  if (stage.status === "LOCKED") return <Empty>The candidate has not reached this stage yet.</Empty>;
  if (stage.status === "AVAILABLE") return <Empty>This stage is open. The candidate has not started it.</Empty>;
  if (q.isLoading) return <Loading />;
  if (!q.data) return <Empty>No attempt recorded yet.</Empty>;
  const a = q.data.attempt;
  const letter = (i: number | null) => (i == null ? "—" : `Option ${String.fromCharCode(65 + i)}`);
  return (
    <div className="space-y-4" data-testid={`result-${stage.stage_type}`}>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-3"><p className="text-xs text-gray-500">Score</p><p className="text-xl font-bold text-gray-900">{a.total_score == null ? "—" : pct(a.total_score, 1)}</p></div>
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-3"><p className="text-xs text-gray-500">Answered</p><p className="text-xl font-bold text-gray-900">{r?.answered ?? "—"} / {r?.total_questions ?? "—"}</p></div>
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-3"><p className="text-xs text-gray-500">Status</p><p className="pt-1"><Badge>{a.status}</Badge></p></div>
        <div className="rounded-lg border border-gray-100 bg-gray-50 p-3"><p className="text-xs text-gray-500">Submitted</p><p className="text-sm font-medium text-gray-900 pt-1">{r?.submitted_at ? new Date(r.submitted_at).toLocaleString() : "In progress"}</p></div>
      </div>
      {stage.stage_type === "CODING_ASSESSMENT" && (
        <p className="text-xs text-gray-600">
          {r?.problems_attempted ?? 0} of {r?.total_questions ?? 0} problems attempted. Scores come from test execution only; hidden test inputs are never shown.
        </p>
      )}
      <Table head={[stage.stage_type === "APTITUDE_ASSESSMENT" ? "Category" : "Type", "Question", "Candidate response", "Score", stage.stage_type === "TECHNICAL_ASSESSMENT" ? "Evaluation" : "Result"]}>
        {q.data.answers.map((x: any) => (
          <tr key={x.answer_id} className="align-top hover:bg-gray-50/50">
            <td className="py-2.5 pr-3"><Badge tone="gray">{questionTypeLabel(x.question_type)}</Badge></td>
            <td className="pr-3 max-w-xs text-xs text-gray-800 leading-relaxed">{x.question_text}</td>
            <td className="pr-3 max-w-xs text-xs text-gray-600">
              {x.question_type === "MCQ" ? (
                <span>{letter(x.selected_option_index)}</span>
              ) : x.question_type === "CODING" ? (
                x.coding ? <span>{x.coding.passed}/{x.coding.total} tests passed ({x.coding.language ?? "—"})</span> : "Not submitted"
              ) : (
                x.answer_text ?? "—"
              )}
            </td>
            <td className="pr-3 text-xs font-semibold">{x.score == null ? "—" : x.score.toFixed(2)}</td>
            <td className="text-xs text-gray-500">
              {x.question_type === "MCQ" ? (
                x.is_correct ? <span className="text-emerald-700 font-bold">✓ Correct</span> : <span className="text-red-600 font-bold">✗ Incorrect</span>
              ) : x.rubric_evaluation ? (
                `Concept accuracy: ${pct(x.rubric_evaluation.concept_accuracy)}${x.rubric_evaluation.missing_concepts?.length ? `; missing: ${x.rubric_evaluation.missing_concepts.join(", ")}` : ""}`
              ) : (
                "—"
              )}
            </td>
          </tr>
        ))}
      </Table>
    </div>
  );
}

function InterviewResult({ stage }: { stage: JourneyStage }) {
  const r = stage.result;
  const turns = useQuery({
    queryKey: ["cand-turns", r?.interview_id],
    enabled: !!r?.interview_id,
    queryFn: () => api.get(`/interviews/${r.interview_id}/turns`).then((x) => x.data),
  });
  if (stage.status === "LOCKED") return <Empty>The candidate has not reached this stage yet.</Empty>;
  if (!r) return <Empty>{stage.status === "AVAILABLE" ? "This stage is open. The candidate has not started it." : "Not taken yet."}</Empty>;
  const hr = stage.stage_type === "HR_INTERVIEW";
  return (
    <div className="space-y-4" data-testid={`result-${stage.stage_type}`}>
      <div className="flex flex-wrap items-center gap-3 text-xs text-gray-600">
        <Badge>{r.status}</Badge>
        <span>{r.answered} of {r.turns} questions answered (planned up to {r.question_budget})</span>
      </div>
      {hr ? (
        <>
          <p className="text-xs text-gray-600 rounded-md bg-gray-50 border border-gray-200 p-2.5">
            Neutral, job-relevant notes for you to read. This stage has no score, fit percentage or personality rating, and it does not affect the skill match.
          </p>
          <div className="space-y-3">
            {(turns.data ?? []).map((t: any) => (
              <div key={t.id} className="border border-gray-200 rounded-lg p-3.5 space-y-2 bg-white">
                <div className="flex items-center justify-between text-xs text-gray-500">
                  <span className="font-semibold text-gray-800">{HR_CATEGORY_LABEL[t.category] ?? t.skill_name ?? "HR question"}</span>
                  <span>via {t.answer_source ?? "text"}</span>
                </div>
                <p className="text-sm font-medium text-gray-900">{t.question_text}</p>
                {t.student_answer_text && (
                  <div className="p-2.5 bg-gray-50 rounded border border-gray-100 text-xs text-gray-800">
                    <p className="font-semibold text-gray-600 mb-0.5">Candidate answer</p>
                    <p className="whitespace-pre-wrap">{t.student_answer_text}</p>
                  </div>
                )}
                {t.rubric_evaluation?.type === "hr_observation" && (
                  <div className="text-xs text-gray-700 space-y-1">
                    {t.rubric_evaluation.summary && <p><span className="font-semibold">Observation:</span> {t.rubric_evaluation.summary}</p>}
                    {t.rubric_evaluation.key_points?.length > 0 && (
                      <ul className="list-disc ml-5">{t.rubric_evaluation.key_points.map((k: string) => <li key={k}>{k}</li>)}</ul>
                    )}
                    <p className="text-gray-500">{t.rubric_evaluation.gave_concrete_example ? "Gave a concrete example." : "Did not give a concrete example."}</p>
                  </div>
                )}
              </div>
            ))}
          </div>
        </>
      ) : (
        <>
          {(r.competencies ?? []).length > 0 && (
            <Table head={["Competency", "Questions asked", "Deepest layer reached", "Average answer score"]}>
              {r.competencies.map((c: any) => (
                <tr key={c.competency}>
                  <td className="py-2 pr-3 font-medium text-gray-900">{c.competency}</td>
                  <td className="pr-3 text-xs">{c.questions}</td>
                  <td className="pr-3 text-xs">{c.deepest_layer ? `${c.deepest_layer} of 5 · ${LAYER_LABEL[c.deepest_layer]}` : "—"}</td>
                  <td className="pr-3 text-xs font-semibold">{c.average_score_pct == null ? "—" : `${c.average_score_pct}%`}</td>
                </tr>
              ))}
            </Table>
          )}
          <div className="space-y-3">
            {(turns.data ?? []).map((t: any) => (
              <div key={t.id} className="border border-gray-200 rounded-lg p-3.5 space-y-2 bg-white">
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
                  <span className="font-semibold text-gray-800">Question {t.turn_index + 1}: {t.skill_name}</span>
                  <div className="flex items-center gap-2">
                    {t.layer && <Badge tone="blue">{`Layer ${t.layer} · ${LAYER_LABEL[t.layer]}`}</Badge>}
                    <Badge tone="gray">{humanize(t.difficulty)}</Badge>
                    <span>via {t.answer_source ?? "text"}</span>
                  </div>
                </div>
                <p className="text-sm text-gray-900 font-medium">{t.question_text}</p>
                {t.student_answer_text && (
                  <div className="p-2.5 bg-gray-50 rounded border border-gray-100 text-xs text-gray-800">
                    <p className="font-semibold text-gray-600 mb-0.5">Candidate answer</p>
                    <p className="whitespace-pre-wrap">{t.student_answer_text}</p>
                  </div>
                )}
                {t.rubric_evaluation && (
                  <div className="flex flex-wrap gap-3 text-xs text-gray-500 pt-1">
                    <span>Accuracy: <b>{pct(t.rubric_evaluation.concept_accuracy)}</b></span>
                    <span>Reasoning: <b>{pct(t.rubric_evaluation.reasoning)}</b></span>
                    <span>Completeness: <b>{pct(t.rubric_evaluation.completeness)}</b></span>
                    <span>Evaluator confidence: <b>{pct(t.rubric_evaluation.evaluator_confidence)}</b></span>
                  </div>
                )}
                {t.reason_for_question && <p className="text-[11px] text-gray-400">{t.reason_for_question}</p>}
              </div>
            ))}
          </div>
        </>
      )}
    </div>
  );
}

/** Round-by-round qualification record with the automatic result, the component breakdown and a controlled human override. */
export function RoundTimeline({ applicationId, stages, onChanged }: { applicationId: string; stages: JourneyStage[]; onChanged: () => void }) {
  const [open, setOpen] = useState<string | null>(null);
  const [form, setForm] = useState<{ stage: string; decision: "ADVANCE" | "HOLD"; reason: string } | null>(null);
  const override = useMutation({
    mutationFn: () => api.post(`/hiring-pipeline/applications/${applicationId}/stages/${form!.stage}/override`, { decision: form!.decision, reason: form!.reason }),
    onSuccess: () => {
      setForm(null);
      onChanged();
    },
  });
  const reeval = useMutation({
    mutationFn: (stage: string) => api.post(`/hiring-pipeline/applications/${applicationId}/stages/${stage}/evaluate`),
    onSuccess: onChanged,
  });
  const resultText = (r: RoundView | null | undefined, s: JourneyStage) => {
    if (s.status === "LOCKED" || s.status === "AVAILABLE") return "Pending";
    if (s.status === "IN_PROGRESS") return "In progress";
    if (!r) return "Completed";
    if (r.override) return r.override.decision === "ADVANCED" ? "Advanced by recruiter" : "Held for review";
    if (r.decision === "MANUAL_REVIEW" && !s.pass_threshold) return "Completed";
    return DECISION_LABEL[r.decision] ?? "Completed";
  };
  return (
    <div className="space-y-2" data-testid="round-timeline">
      {stages.map((s) => {
        const r = s.round;
        const scored = r && r.score != null;
        const canOverride = !!r && r.decision !== "EVALUATION_PENDING" && r.threshold != null && s.status === "COMPLETED";
        const advancing = r && r.decision === "QUALIFIED";
        return (
          <div key={s.stage_id} className="rounded-lg border border-gray-200 bg-white" data-testid={`round-${s.stage_type}`}>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 p-3 text-sm">
              <span className="w-44 font-medium text-gray-900">{s.label}</span>
              <span className="w-24 tabular-nums text-gray-900">{scored ? fmtScore(r!.score) : "—"}</span>
              <span className="w-28 text-xs text-gray-500">{s.pass_threshold != null ? `Requirement ${fmtScore(s.pass_threshold)}` : s.kind === "assessment" || s.stage_type === "TECHNICAL_INTERVIEW" ? "No threshold" : "Manual decision"}</span>
              <span className="flex-1 font-medium text-gray-800">{resultText(r, s)}</span>
              {r?.evaluated_at && <span className="text-xs text-gray-400">{new Date(r.evaluated_at).toLocaleString()}</span>}
              {r && (
                <button type="button" className="text-xs font-medium text-blue-700 hover:underline" aria-expanded={open === s.stage_id} onClick={() => setOpen(open === s.stage_id ? null : s.stage_id)}>
                  {open === s.stage_id ? "Hide details" : "Details"}
                </button>
              )}
            </div>
            {open === s.stage_id && r && (
              <div className="space-y-3 border-t border-gray-100 p-3 text-xs text-gray-700">
                {Object.keys(r.components ?? {}).length > 0 ? (
                  <table className="w-full">
                    <thead><tr className="text-left text-gray-500"><th className="py-1 font-medium">Component</th><th className="font-medium">Score</th><th className="font-medium">Weight</th></tr></thead>
                    <tbody>
                      {Object.entries(r.components!).map(([k, c]) => (
                        <tr key={k}><td className="py-1">{COMPONENT_LABEL[k] ?? humanize(k)}</td><td>{fmtScore(c.score)}</td><td>{c.weight != null ? `${c.weight}%` : "—"}</td></tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p>No component breakdown for this round.</p>
                )}
                <p>
                  Automatic result: <b>{DECISION_LABEL[r.automatic_decision ?? r.decision]}</b>
                  {r.threshold != null && <> (score {fmtScore(r.score)} against a requirement of {fmtScore(r.threshold)})</>}. Evaluation {r.evaluation_version}.
                </p>
                {r.override && (
                  <p className="rounded-md border border-amber-200 bg-amber-50 p-2 text-amber-900" data-testid="override-note">
                    Override: {r.override.decision === "ADVANCED" ? "advanced by recruiter" : "held for review"} on {new Date(r.override.at).toLocaleString()}. Reason: “{r.override.reason}”. Previous decision: {DECISION_LABEL[r.override.previous] ?? r.override.previous}.
                  </p>
                )}
                {canOverride && (
                  <div className="flex flex-wrap gap-2">
                    {!advancing && <Button size="sm" onClick={() => setForm({ stage: s.stage_type, decision: "ADVANCE", reason: "" })} data-testid={`override-advance-${s.stage_type}`}>Advance to next round</Button>}
                    {advancing && <Button size="sm" variant="secondary" onClick={() => setForm({ stage: s.stage_type, decision: "HOLD", reason: "" })}>Hold for manual review</Button>}
                    <Button size="sm" variant="ghost" onClick={() => reeval.mutate(s.stage_type)} disabled={reeval.isPending}>Re-evaluate with current settings</Button>
                  </div>
                )}
              </div>
            )}
            {form?.stage === s.stage_type && (
              <div className="space-y-2 border-t border-gray-100 bg-gray-50 p-3" data-testid="override-form">
                <label className="block text-xs font-medium text-gray-700" htmlFor="override-reason">
                  Reason for {form.decision === "ADVANCE" ? "advancing this candidate despite the score" : "holding this candidate"} (required, kept in the audit trail)
                </label>
                <textarea id="override-reason" className="w-full rounded-md border border-gray-300 p-2 text-sm" rows={2} value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })} />
                <div className="flex gap-2">
                  <Button size="sm" onClick={() => override.mutate()} disabled={override.isPending || form.reason.trim().length < 5}>Confirm</Button>
                  <Button size="sm" variant="ghost" onClick={() => setForm(null)}>Cancel</Button>
                </div>
              </div>
            )}
          </div>
        );
      })}
      <ErrorBox error={override.error || reeval.error} />
    </div>
  );
}

export function StageResultCard({ applicationId, stage }: { applicationId: string; stage: JourneyStage }) {
  return (
    <Card title={stage.label} description={stage.completed_at ? `Completed ${new Date(stage.completed_at).toLocaleString()}` : undefined} actions={<Badge>{stage.status}</Badge>}>
      {stage.kind === "assessment" ? <AssessmentResult applicationId={applicationId} stage={stage} /> : <InterviewResult stage={stage} />}
    </Card>
  );
}

