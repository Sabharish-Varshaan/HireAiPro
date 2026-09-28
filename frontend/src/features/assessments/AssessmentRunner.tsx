import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading, pct } from "../../components/ui";

type Saved = { answer_id: string; answer_text?: string | null; selected_option_index?: number | null };

const STDIN_TEMPLATE = "import ast, sys\n\n# Each test's input arrives on stdin; print your answer.\ndata = ast.literal_eval(sys.stdin.read())\n\n# your solution here\n";

export function AssessmentRunner({ assessmentId, applicationId, onSubmitted }: {
  assessmentId: string; applicationId: string; onSubmitted: () => void;
}) {
  const qc = useQueryClient();
  const detail = useQuery({ queryKey: ["assessment-detail", assessmentId], queryFn: () => api.get(`/assessments/${assessmentId}`).then((r) => r.data) });
  // POST is get-or-create, so a refresh resumes the same attempt.
  const attempt = useQuery({
    queryKey: ["attempt", applicationId],
    queryFn: () => api.post(`/assessments/${assessmentId}/attempts`, { application_id: applicationId }).then((r) => r.data),
    enabled: false,
  });
  const existing = useQuery({
    queryKey: ["attempt-by-app", applicationId],
    queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`).then((r) => r.data),
  });
  const attemptId: string | undefined = existing.data?.attempt?.id ?? attempt.data?.id;
  const status: string | undefined = existing.data?.attempt?.status ?? attempt.data?.status;

  const [saved, setSaved] = useState<Record<string, Saved>>({});
  const [code, setCode] = useState<Record<string, string>>({});
  const [runs, setRuns] = useState<Record<string, any>>({});
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const timers = useRef<Record<string, number>>({});

  useEffect(() => {
    if (!existing.data?.answers) return;
    const m: Record<string, Saved> = {};
    for (const a of existing.data.answers) m[a.assessment_question_id] = a;
    setSaved(m);
  }, [existing.data]);

  const save = useMutation({
    mutationFn: (p: { assessment_question_id: string; answer_text?: string; selected_option_index?: number }) =>
      api.put(`/assessments/attempts/${attemptId}/answers`, p).then((r) => ({ ...p, answer_id: r.data.answer_id })),
    onMutate: () => setSaveState("saving"),
    onSuccess: (r) => { setSaveState("saved"); setSaved((s) => ({ ...s, [r.assessment_question_id]: { ...s[r.assessment_question_id], ...r } })); },
    onError: () => setSaveState("error"),
  });
  const autosave = (aqId: string, payload: any, delay = 800) => {
    window.clearTimeout(timers.current[aqId]);
    timers.current[aqId] = window.setTimeout(() => save.mutate({ assessment_question_id: aqId, ...payload }), delay);
  };
  const runCode = useMutation({
    mutationFn: async ({ aqId, questionId, source }: { aqId: string; questionId: string; source: string }) => {
      let answerId = saved[aqId]?.answer_id;
      if (!answerId) answerId = (await api.put(`/assessments/attempts/${attemptId}/answers`, { assessment_question_id: aqId })).data.answer_id;
      const r = await api.post("/coding/submit", { assessment_answer_id: answerId, question_id: questionId, language: "python", source_code: source });
      return { aqId, data: r.data };
    },
    onSuccess: ({ aqId, data }) => setRuns((s) => ({ ...s, [aqId]: data })),
  });
  const submit = useMutation({
    mutationFn: () => api.post(`/assessments/attempts/${attemptId}/submit`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["attempt-by-app", applicationId] }); onSubmitted(); },
  });

  if (detail.isLoading || existing.isLoading) return <Loading />;
  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.refetch} />;
  const questions = detail.data.sections.flatMap((s: any) => s.questions.map((q: any) => ({ ...q, section: s.title })));
  const answered = questions.filter((q: any) => {
    const s = saved[q.id];
    return s && ((s.answer_text && s.answer_text.trim()) || s.selected_option_index != null) || runs[q.id];
  }).length;

  if (status === "SCORED") {
    return (
      <div className="space-y-2">
        <p className="text-sm">Submitted. Score: <b>{pct(existing.data?.attempt?.total_score, 1)}</b></p>
        <ul className="text-xs text-gray-600 space-y-1">
          {(existing.data?.answers ?? []).map((a: any) => (
            <li key={a.answer_id}><Badge tone="gray">{a.question_type}</Badge> {a.question_text?.slice(0, 90)} — {a.score == null ? "—" : a.score.toFixed(2)}
              {a.coding && ` · ${a.coding.passed}/${a.coding.total} tests · ${a.coding.backends.join(", ")}`}</li>
          ))}
        </ul>
      </div>
    );
  }
  if (!attemptId) {
    return (
      <div className="space-y-2">
        <p className="text-sm text-gray-600">{questions.length} questions · about {detail.data.total_duration_minutes} minutes. Answers save automatically.</p>
        <Button onClick={() => attempt.refetch().then(() => existing.refetch())} disabled={attempt.isFetching}>{attempt.isFetching ? "Starting…" : "Start assessment"}</Button>
        <ErrorBox error={attempt.error} />
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between text-xs text-gray-500 sticky top-0 bg-white py-1">
        <span>Progress: {answered}/{questions.length} answered</span>
        <span>{saveState === "saving" ? "Saving…" : saveState === "saved" ? "All changes saved" : saveState === "error" ? "Save failed — retrying on next change" : ""}</span>
      </div>
      {questions.map((aq: any, i: number) => {
        const q = aq.question;
        const s = saved[aq.id];
        const run = runs[aq.id];
        return (
          <div key={aq.id} className="border border-gray-200 rounded-md p-3 space-y-2">
            <p className="text-xs text-gray-500">Q{i + 1} · {aq.section} · {q.question_type} · {q.difficulty}</p>
            <p className="text-sm text-gray-900 whitespace-pre-wrap">{q.question_text}</p>
            {q.question_type === "MCQ" && q.options?.map((opt: string, idx: number) => (
              <label key={idx} className="flex items-center gap-2 text-sm">
                <input type="radio" name={aq.id} checked={s?.selected_option_index === idx}
                  onChange={() => { setSaved((m) => ({ ...m, [aq.id]: { ...m[aq.id], selected_option_index: idx } as Saved })); save.mutate({ assessment_question_id: aq.id, selected_option_index: idx }); }} />
                {opt}
              </label>
            ))}
            {q.question_type === "TECHNICAL" && (
              <textarea className="w-full border border-gray-300 rounded-md p-2 text-sm" rows={5} defaultValue={s?.answer_text ?? ""}
                placeholder="Your answer…" onChange={(e) => autosave(aq.id, { answer_text: e.target.value })} />
            )}
            {q.question_type === "CODING" && (
              <div className="space-y-2">
                <Editor height="220px" defaultLanguage="python" defaultValue={s?.answer_text || q.starter_code || STDIN_TEMPLATE}
                  onChange={(v) => setCode((c) => ({ ...c, [aq.id]: v ?? "" }))} options={{ minimap: { enabled: false }, fontSize: 13 }} />
                <Button variant="secondary" disabled={runCode.isPending}
                  onClick={() => runCode.mutate({ aqId: aq.id, questionId: q.id, source: code[aq.id] ?? s?.answer_text ?? q.starter_code ?? "" })}>
                  {runCode.isPending ? "Running…" : "Run tests"}
                </Button>
                {run && (
                  <div className="text-xs space-y-1">
                    <p><b>{run.passed_count}/{run.total_count}</b> hidden tests passed</p>
                    {run.tests.map((t: any) => (
                      <p key={t.index}>Test {t.index + 1}: {t.passed ? "passed" : "failed"} · <Badge>{t.execution_backend}</Badge>
                        {t.stderr && <span className="text-red-600"> {t.stderr.slice(0, 160)}</span>}</p>
                    ))}
                    {run.tests.some((t: any) => t.execution_backend === "local_fallback") && (
                      <p className="text-amber-700">Executed by the local development fallback (not the Judge0 sandbox): {run.tests[0].fallback_reason}. Development only — no sandbox isolation.</p>
                    )}
                  </div>
                )}
              </div>
            )}
          </div>
        );
      })}
      <ErrorBox error={save.error || runCode.error || submit.error} />
      <Button onClick={() => { if (window.confirm(`Submit the assessment? ${answered}/${questions.length} answered. You can't change answers afterwards.`)) submit.mutate(); }}
        disabled={submit.isPending}>{submit.isPending ? "Scoring…" : "Submit assessment"}</Button>
    </div>
  );
}
