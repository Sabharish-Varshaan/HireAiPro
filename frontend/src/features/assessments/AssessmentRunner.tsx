import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { CodingQuestion } from "./CodingQuestion";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading } from "../../components/ui";

type Saved = { answer_id: string; answer_text?: string | null; selected_option_index?: number | null };

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
  const saveAndGetAnswerId = async (aqId: string, text: string) => {
    window.clearTimeout(timers.current[aqId]);
    const r = await save.mutateAsync({ assessment_question_id: aqId, answer_text: text });
    return r.answer_id as string;
  };
  const submit = useMutation({
    mutationFn: () => api.post(`/assessments/attempts/${attemptId}/submit`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["attempt-by-app", applicationId] }); onSubmitted(); },
  });

  if (detail.isLoading || existing.isLoading) return <Loading />;
  if (detail.error) return <ErrorBox error={detail.error} onRetry={detail.refetch} />;
  const questions = detail.data.sections.flatMap((s: any) => s.questions.map((q: any) => ({ ...q, section: s.title })));
  const answered = questions.filter((q: any) => {
    const s = saved[q.id];
    return s && ((s.answer_text && s.answer_text.trim()) || s.selected_option_index != null);
  }).length;

  if (status === "SCORED") {
    return (
      <div className="space-y-2">
        <p className="text-sm font-medium">Assessment completed</p>
        <p className="text-xs text-gray-500">Your answers were submitted for review. Results are shared with the employer; your development feedback is under "Your skills".</p>
        <ul className="text-xs text-gray-600 space-y-1">
          {(existing.data?.answers ?? []).map((a: any) => (
            <li key={a.answer_id}><Badge tone="gray">{a.question_type}</Badge> {a.question_text?.slice(0, 90)} — {a.completed ? "answered" : "not answered"}
              {a.coding && ` · coding: ${a.coding.status === "ALL_TESTS_PASSED" ? "all tests passed" : a.coding.status === "SOME_TESTS_FAILED" ? "some tests failed" : "error"} (${a.coding.language})`}</li>
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
              <CodingQuestion aqId={aq.id} question={q} savedText={s?.answer_text}
                saveAndGetAnswerId={(text) => saveAndGetAnswerId(aq.id, text)} />
            )}
          </div>
        );
      })}
      <ErrorBox error={save.error || submit.error} />
      <Button onClick={() => { if (window.confirm(`Submit the assessment? ${answered}/${questions.length} answered. You can't change answers afterwards.`)) submit.mutate(); }}
        disabled={submit.isPending}>{submit.isPending ? "Scoring…" : "Submit assessment"}</Button>
    </div>
  );
}
