import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { CodingQuestion } from "./CodingQuestion";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading, apiError } from "../../components/ui";

type Ans = { answer_id: string | null; answer_text: string | null; selected_option_index: number | null; marked_for_review: boolean };

const fmtClock = (s: number) => `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ""}${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
const isAnswered = (type: string, a?: Ans) => !!a && (type === "MCQ" ? a.selected_option_index != null : !!(a.answer_text && a.answer_text.trim()));

export function AssessmentRunner({ assessmentId, applicationId, onSubmitted }: {
  assessmentId: string; applicationId: string; onSubmitted: () => void;
}) {
  const qc = useQueryClient();
  const overview = useQuery({ queryKey: ["assessment-overview", assessmentId], queryFn: () => api.get(`/assessments/${assessmentId}/overview`).then((r) => r.data) });
  const existing = useQuery({ queryKey: ["attempt-by-app", applicationId], queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`).then((r) => r.data) });
  const attemptId: string | undefined = existing.data?.attempt?.id;
  const status: string | undefined = existing.data?.attempt?.status;
  const start = useMutation({
    mutationFn: () => api.post(`/assessments/${assessmentId}/attempts`, { application_id: applicationId }).then((r) => r.data),
    onSuccess: () => existing.refetch(),
  });
  const session = useQuery({ queryKey: ["attempt-session", attemptId], enabled: !!attemptId && status === "IN_PROGRESS", refetchOnWindowFocus: false, staleTime: Infinity,
    queryFn: () => api.get(`/assessments/attempts/${attemptId}`).then((r) => ({ ...r.data, clockOffset: new Date(r.data.server_time).getTime() - Date.now() })) });

  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, Ans>>({});
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [confirming, setConfirming] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const timers = useRef<Record<string, number>>({});
  const autoSubmitted = useRef(false);

  const flat: any[] = (session.data?.sections ?? []).flatMap((s: any) => s.questions.map((q: any) => ({ ...q, section: s.title })));

  useEffect(() => {
    if (!session.data) return;
    const m: Record<string, Ans> = {};
    for (const q of flat) m[q.id] = q.answer;
    setAnswers(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.data]);

  const submit = useMutation({
    mutationFn: () => api.post(`/assessments/attempts/${attemptId}/submit`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["attempt-by-app", applicationId] }); onSubmitted(); },
  });
  const doSubmit = useCallback(() => { if (!submit.isPending && !submit.isSuccess) submit.mutate(); }, [submit]);

  // Presentation only: the server's expires_at is authoritative and enforced on every write.
  useEffect(() => {
    if (!session.data?.expires_at) return;
    const end = new Date(session.data.expires_at).getTime();
    const tick = () => {
      const left = Math.max(0, Math.round((end - (Date.now() + session.data.clockOffset)) / 1000));
      setRemaining(left);
      if (left === 0 && !autoSubmitted.current) { autoSubmitted.current = true; doSubmit(); }
    };
    tick();
    const t = window.setInterval(tick, 1000);
    return () => window.clearInterval(t);
  }, [session.data, doSubmit]);

  const save = useMutation({
    mutationFn: (p: { assessment_question_id: string; answer_text?: string; selected_option_index?: number; marked_for_review?: boolean }) =>
      api.put(`/assessments/attempts/${attemptId}/answers`, p).then((r) => ({ p, answer_id: r.data.answer_id as string })),
    onMutate: () => setSaveState("saving"),
    onSuccess: ({ p, answer_id }) => {
      setSaveState("saved");
      setAnswers((a) => ({ ...a, [p.assessment_question_id]: { ...a[p.assessment_question_id], answer_id } }));
    },
    onError: (e: any) => {
      setSaveState("error");
      if (e?.response?.data?.detail?.code === "ATTEMPT_EXPIRED" && !autoSubmitted.current) { autoSubmitted.current = true; doSubmit(); }
    },
  });
  const patch = (id: string, p: Partial<Ans>) => setAnswers((a) => ({ ...a, [id]: { ...a[id], ...p } }));
  const autosave = (id: string, payload: any, delay = 800) => {
    window.clearTimeout(timers.current[id]);
    timers.current[id] = window.setTimeout(() => save.mutate({ assessment_question_id: id, ...payload }), delay);
  };
  const saveAndGetAnswerId = async (id: string, text: string) => {
    window.clearTimeout(timers.current[id]);
    patch(id, { answer_text: text });
    return (await save.mutateAsync({ assessment_question_id: id, answer_text: text })).answer_id;
  };

  if (overview.isLoading || existing.isLoading) return <Loading />;
  if (overview.error) return <ErrorBox error={overview.error} onRetry={overview.refetch} />;

  if (status === "SCORED" || status === "SUBMITTED") {
    return (
      <div className="space-y-2" data-testid="assessment-completed">
        <p className="text-sm font-medium">Assessment completed</p>
        <p className="text-xs text-gray-500">Your answers were submitted for review. Results are shared with the employer; your development feedback is under "Skills &amp; career".</p>
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
    const o = overview.data;
    return (
      <div className="space-y-3" data-testid="assessment-intro">
        <p className="text-sm font-medium">{o.title}</p>
        <ul className="text-sm text-gray-700 list-disc pl-5 space-y-1">
          <li><b>{o.question_count}</b> questions ({o.types.MCQ} multiple choice, {o.types.TECHNICAL} written, {o.types.CODING} coding).</li>
          <li>Time limit: <b>{o.duration_minutes} minutes</b>. The timer starts when you press Start and cannot be paused or reset. Refreshing or opening another tab does not add time.</li>
          <li>Answers save automatically. You can move between questions and mark any for review before you submit.</li>
          <li>When time runs out, your saved answers are submitted automatically.</li>
        </ul>
        <Button onClick={() => start.mutate()} disabled={start.isPending}>{start.isPending ? "Starting…" : "Start assessment"}</Button>
        <ErrorBox error={start.error} />
      </div>
    );
  }

  if (session.isLoading || !session.data) return <Loading label="Loading your assessment…" />;
  if (session.error) return <ErrorBox error={session.error} onRetry={session.refetch} />;

  const current = flat[Math.min(idx, flat.length - 1)];
  const q = current.question;
  const a = answers[current.id];
  const counts = flat.reduce((c, x) => {
    const ans = answers[x.id];
    return { answered: c.answered + (isAnswered(x.question.question_type, ans) ? 1 : 0), marked: c.marked + (ans?.marked_for_review ? 1 : 0) };
  }, { answered: 0, marked: 0 });
  const low = remaining != null && remaining <= 300;

  return (
    <div className="space-y-4" data-testid="assessment-active">
      <div className="flex items-center justify-between text-xs sticky top-0 bg-white py-2 border-b border-gray-100 z-10">
        <span className="text-gray-600">Answered {counts.answered}/{flat.length} · Marked {counts.marked}</span>
        <span className="text-gray-500">{saveState === "saving" ? "Saving…" : saveState === "saved" ? "All changes saved" : saveState === "error" ? "Save failed — will retry on next change" : ""}</span>
        <span className={`font-mono text-sm px-2 py-0.5 rounded ${low ? "bg-red-100 text-red-700" : "bg-gray-100 text-gray-700"}`} data-testid="timer" aria-label="time remaining">
          {remaining == null ? "--:--" : fmtClock(remaining)}</span>
      </div>

      <div className="flex flex-wrap gap-1" data-testid="navigator">
        {flat.map((x, i) => {
          const ans = answers[x.id]; const done = isAnswered(x.question.question_type, ans);
          return (
            <button key={x.id} onClick={() => setIdx(i)} title={`Question ${i + 1}: ${done ? "answered" : "unanswered"}${ans?.marked_for_review ? ", marked" : ""}`}
              data-state={`${done ? "answered" : "unanswered"}${ans?.marked_for_review ? "+marked" : ""}`}
              className={`w-8 h-8 text-xs rounded border ${i === idx ? "ring-2 ring-gray-900" : ""} ${ans?.marked_for_review ? "border-amber-500 bg-amber-100" : done ? "border-green-600 bg-green-100" : "border-gray-300 bg-white"}`}>{i + 1}</button>);
        })}
      </div>
      <p className="text-[11px] text-gray-500">Green = answered · Amber = marked for review · White = not answered</p>

      <div className="border border-gray-200 rounded-md p-3 space-y-2">
        <p className="text-xs text-gray-500">Question {idx + 1} of {flat.length} · {current.section} · {q.question_type}</p>
        <p className="text-sm text-gray-900 whitespace-pre-wrap">{q.question_text}</p>
        {q.question_type === "MCQ" && q.options?.map((opt: string, i: number) => (
          <label key={`${current.id}-${i}`} className="flex items-center gap-2 text-sm">
            <input type="radio" name={current.id} checked={a?.selected_option_index === i}
              onChange={() => { patch(current.id, { selected_option_index: i }); save.mutate({ assessment_question_id: current.id, selected_option_index: i }); }} />
            {opt}
          </label>
        ))}
        {q.question_type === "TECHNICAL" && (
          <textarea key={current.id} className="w-full border border-gray-300 rounded-md p-2 text-sm" rows={7} defaultValue={a?.answer_text ?? ""}
            placeholder="Your answer…" onChange={(e) => { patch(current.id, { answer_text: e.target.value }); autosave(current.id, { answer_text: e.target.value }); }} />
        )}
        {q.question_type === "CODING" && (
          <CodingQuestion key={current.id} aqId={current.id} question={q} savedText={a?.answer_text}
            saveAndGetAnswerId={(text) => saveAndGetAnswerId(current.id, text)} />
        )}
        <div className="flex items-center gap-2 pt-1">
          <Button variant="secondary" onClick={() => setIdx((i) => Math.max(0, i - 1))} disabled={idx === 0}>Previous</Button>
          <Button variant="secondary" onClick={() => setIdx((i) => Math.min(flat.length - 1, i + 1))} disabled={idx >= flat.length - 1}>Next</Button>
          <Button variant="secondary" onClick={() => { const v = !a?.marked_for_review; patch(current.id, { marked_for_review: v }); save.mutate({ assessment_question_id: current.id, marked_for_review: v }); }}>
            {a?.marked_for_review ? "Unmark review" : "Mark for review"}</Button>
        </div>
      </div>

      <ErrorBox error={submit.error} />
      {!confirming ? (
        <Button onClick={() => setConfirming(true)} disabled={submit.isPending}>Review and submit</Button>
      ) : (
        <div className="border border-amber-300 bg-amber-50 rounded-md p-3 space-y-2 text-sm" data-testid="submit-confirm">
          <p><b>{counts.answered}</b> of {flat.length} answered · <b>{flat.length - counts.answered}</b> unanswered · <b>{counts.marked}</b> marked for review.</p>
          <p className="text-xs text-gray-600">You cannot change answers after submitting.</p>
          <div className="flex gap-2">
            <Button onClick={doSubmit} disabled={submit.isPending}>{submit.isPending ? "Submitting…" : "Submit assessment"}</Button>
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={submit.isPending}>Keep working</Button>
          </div>
        </div>
      )}
      {save.error && !(save.error as any)?.response?.data?.detail?.code && <p className="text-xs text-red-600">{apiError(save.error)}</p>}
    </div>
  );
}
