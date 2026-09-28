import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls, pct } from "../../components/ui";

export function MatchExplanation({ match }: { match: any }) {
  const w = match.weights ?? {};
  const parts = [
    ["Required skill fit", match.required_skill_fit, w.required],
    ["Preferred skill fit", match.preferred_skill_fit, w.preferred],
    ["Evidence confidence", match.evidence_confidence, w.evidence_confidence],
    ["Semantic relevance", match.semantic_relevance, w.semantic_relevance],
  ] as const;
  const list = (title: string, items: any[], tone: string) => (
    <div>
      <p className="text-xs font-medium text-gray-700 mb-1">{title} ({items?.length ?? 0})</p>
      <div className="flex flex-wrap gap-1">
        {(items ?? []).map((s) => <Badge key={s.skill_id} tone={tone}>{`${s.skill_name} · fit ${pct(s.fit)}`}</Badge>)}
        {(items ?? []).length === 0 && <span className="text-xs text-gray-400">none</span>}
      </div>
    </div>
  );
  return (
    <div className="space-y-3">
      <div className="flex items-baseline gap-3">
        <span className="text-3xl font-semibold">{pct(match.match_score, 1)}</span>
        <span className="text-xs text-gray-500">{match.matching_version} · deterministic formula, no LLM</span>
      </div>
      <Table head={["Component", "Value", "Weight", "Contribution"]}>
        {parts.map(([label, v, wt]) => (
          <tr key={label}>
            <td className="py-1 pr-3">{label}</td><td className="pr-3">{pct(v, 1)}</td>
            <td className="pr-3">{wt != null ? pct(wt) : "—"}</td>
            <td>{wt != null ? pct((v as number) * (wt as number), 1) : "—"}</td>
          </tr>
        ))}
      </Table>
      {list("Strong skills", match.strong_skills, "green")}
      {list("Partial skills", match.partial_skills, "amber")}
      {list("Missing skills", match.missing_skills, "red")}
    </div>
  );
}

const DECISIONS: Record<string, string[]> = {
  APPLIED: ["ASSESSMENT_PENDING", "REJECTED"],
  ASSESSMENT_PENDING: ["REJECTED"],
  ASSESSMENT_COMPLETED: ["UNDER_REVIEW", "REJECTED"],
  INTERVIEW_PENDING: ["REJECTED"],
  INTERVIEW_COMPLETED: ["UNDER_REVIEW", "REJECTED"],
  UNDER_REVIEW: ["SHORTLISTED", "REJECTED"],
  SHORTLISTED: ["OFFER", "REJECTED"],
};

const DECISION_LABEL: Record<string, string> = { SHORTLISTED: "Shortlist", REJECTED: "Reject", OFFER: "Make offer", UNDER_REVIEW: "Move to review" };

export default function CandidatePage() {
  const { applicationId } = useParams();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const app = useQuery({ queryKey: ["application", applicationId], queryFn: () => api.get(`/applications/${applicationId}`).then((r) => r.data) });
  const history = useQuery({ queryKey: ["history", applicationId], queryFn: () => api.get(`/applications/${applicationId}/history`).then((r) => r.data) });
  const match = useQuery({
    queryKey: ["match", applicationId], retry: false,
    queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data),
  });
  const sid = app.data?.student_id;
  const skills = useQuery({ queryKey: ["cand-skills", sid], enabled: !!sid, queryFn: () => api.get(`/evidence/students/${sid}/skills`).then((r) => r.data) });
  const evidence = useQuery({ queryKey: ["cand-evidence", sid], enabled: !!sid, queryFn: () => api.get(`/evidence/students/${sid}/evidence`).then((r) => r.data) });
  const attempt = useQuery({ queryKey: ["cand-attempt", applicationId], queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`).then((r) => r.data) });
  const interview = useQuery({ queryKey: ["cand-interview", applicationId], queryFn: () => api.get(`/interviews/by-application/${applicationId}`).then((r) => r.data) });
  const turns = useQuery({ queryKey: ["cand-turns", interview.data?.id], enabled: !!interview.data?.id,
    queryFn: () => api.get(`/interviews/${interview.data.id}/turns`).then((r) => r.data) });

  const compute = useMutation({
    mutationFn: () => api.post(`/matching/applications/${applicationId}/compute`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["match", applicationId] }),
  });
  const decide = useMutation({
    mutationFn: (status: string) => api.put(`/applications/${applicationId}/status`, { status, note: note || null }),
    onSuccess: () => { setNote(""); qc.invalidateQueries({ queryKey: ["application", applicationId] }); qc.invalidateQueries({ queryKey: ["history", applicationId] }); },
  });

  if (app.isLoading) return <Loading />;
  if (app.error) return <ErrorBox error={app.error} onRetry={app.refetch} />;
  const a = app.data;
  const matchMissing = (match.error as any)?.response?.status === 404;

  return (
    <div className="max-w-5xl space-y-5">
      <div>
        <Link to={`/company/jobs/${a.job_id}`} className="text-xs text-gray-500 underline">← {a.job_title}</Link>
        <div className="flex items-center gap-3">
          <h1 className="text-lg font-semibold">{a.student_name}</h1><Badge>{a.status}</Badge>
        </div>
      </div>

      <Card title="Decision">
        <div className="flex flex-wrap items-center gap-2">
          <input className={`${inputCls} max-w-sm`} placeholder="Note (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
          {(DECISIONS[a.status] ?? []).map((s) => (
            <Button key={s} variant={s === "REJECTED" ? "danger" : "primary"} onClick={() => decide.mutate(s)} disabled={decide.isPending}>
              {DECISION_LABEL[s] ?? s.replaceAll("_", " ").toLowerCase()}
            </Button>
          ))}
          {(DECISIONS[a.status] ?? []).length === 0 && <span className="text-sm text-gray-500">No recruiter decision available in this state.</span>}
        </div>
        <ErrorBox error={decide.error} />
        <ol className="text-xs text-gray-600 space-y-1">
          {(history.data ?? []).map((h: any, i: number) => (
            <li key={i}>{new Date(h.at).toLocaleString()} — {h.from ?? "∅"} → <b>{h.to}</b>{h.by_system ? " (system)" : ""}{h.note ? ` · ${h.note}` : ""}</li>
          ))}
        </ol>
      </Card>

      <Card title="Match explanation" actions={<Button variant="secondary" onClick={() => compute.mutate()} disabled={compute.isPending}>Recompute</Button>}>
        {match.isLoading && <Loading />}
        {matchMissing && <Empty>Not computed yet — computed automatically when the interview completes, or click Recompute.</Empty>}
        {match.data && <MatchExplanation match={match.data} />}
        <ErrorBox error={compute.error} />
      </Card>

      <Card title="Verified skill profile (SkillEstimator)">
        {(skills.data ?? []).length === 0 ? <Empty>No verified skills yet.</Empty> : (
          <Table head={["Skill", "Level", "Confidence", "Evidence", "Scoring"]}>
            {skills.data.map((s: any) => (
              <tr key={s.skill_id}><td className="py-1 pr-3">{s.skill_name}</td><td className="pr-3">{pct(s.estimated_level)}</td>
                <td className="pr-3">{pct(s.confidence)}</td><td className="pr-3">{s.evidence_count}</td><td className="text-xs text-gray-500">{s.scoring_version}</td></tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Evidence">
        {(evidence.data ?? []).length === 0 ? <Empty>No evidence.</Empty> : (
          <Table head={["Skill", "Source", "Score", "Confidence", "Difficulty", "When"]}>
            {evidence.data.map((e: any) => (
              <tr key={e.id}><td className="py-1 pr-3">{e.skill_name}</td>
                <td className="pr-3"><Badge tone={e.source_type === "RESUME_CLAIM" ? "gray" : "blue"}>{e.source_type === "RESUME_CLAIM" ? "RESUME_CLAIM (unverified, weight 0)" : e.source_type}</Badge></td>
                <td className="pr-3">{pct(e.normalized_score)}</td><td className="pr-3">{pct(e.confidence)}</td>
                <td className="pr-3">{e.difficulty ?? "—"}</td><td className="text-xs text-gray-500">{new Date(e.created_at).toLocaleString()}</td></tr>
            ))}
          </Table>
        )}
      </Card>

      <Card title="Assessment" actions={attempt.data ? <Badge>{attempt.data.attempt.status}</Badge> : null}>
        {!attempt.data ? <Empty>Not started.</Empty> : (
          <>
            <p className="text-sm">Total score: <b>{pct(attempt.data.attempt.total_score, 1)}</b></p>
            <Table head={["Type", "Question", "Answer", "Score", "Evaluation"]}>
              {attempt.data.answers.map((x: any) => (
                <tr key={x.answer_id} className="align-top">
                  <td className="py-2 pr-3"><Badge tone="gray">{x.question_type}</Badge></td>
                  <td className="pr-3 max-w-xs">{x.question_text}</td>
                  <td className="pr-3 max-w-xs text-xs text-gray-600">
                    {x.question_type === "MCQ" ? `option ${x.selected_option_index ?? "—"} ${x.is_correct ? "✓" : "✗"}` :
                      x.question_type === "CODING" ? (x.coding ? `${x.coding.passed}/${x.coding.total} tests · ${x.coding.backends.join(", ")}` : "not run") :
                        (x.answer_text ?? "—")}
                  </td>
                  <td className="pr-3">{x.score == null ? "—" : x.score.toFixed(2)}</td>
                  <td className="text-xs text-gray-500">{x.rubric_evaluation ? `accuracy ${pct(x.rubric_evaluation.concept_accuracy)}; missing: ${(x.rubric_evaluation.missing_concepts ?? []).join(", ") || "—"}` : "—"}</td>
                </tr>
              ))}
            </Table>
          </>
        )}
      </Card>

      <Card title="Interview" actions={interview.data ? <Badge>{interview.data.status}</Badge> : null}>
        {!interview.data ? <Empty>Not started.</Empty> : (turns.data ?? []).map((t: any) => (
          <div key={t.id} className="border border-gray-100 rounded p-2 text-sm">
            <p className="text-xs text-gray-500">Turn {t.turn_index + 1} · {t.skill_name} · {t.difficulty} · answered via {t.answer_source ?? "—"}</p>
            <p>{t.question_text}</p>
            <p className="text-xs text-gray-500">Why: {t.reason_for_question}</p>
            {t.student_answer_text && <p className="text-gray-700 mt-1">“{t.student_answer_text}”</p>}
            {t.rubric_evaluation && <p className="text-xs text-gray-500">accuracy {pct(t.rubric_evaluation.concept_accuracy)} · reasoning {pct(t.rubric_evaluation.reasoning)} · evaluator confidence {pct(t.rubric_evaluation.evaluator_confidence)}</p>}
          </div>
        ))}
      </Card>
    </div>
  );
}
