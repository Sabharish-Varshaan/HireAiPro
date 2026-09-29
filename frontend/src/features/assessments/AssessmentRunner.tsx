import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { CodingQuestion } from "./CodingQuestion";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading, ProgressBar, apiError, questionTypeLabel } from "../../components/ui";

type Ans = {
  answer_id: string | null;
  answer_text: string | null;
  selected_option_index: number | null;
  marked_for_review: boolean;
};

const fmtClock = (s: number) =>
  `${Math.floor(s / 3600) ? `${Math.floor(s / 3600)}:` : ""}${String(
    Math.floor((s % 3600) / 60)
  ).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;

const isAnswered = (type: string, a?: Ans) =>
  !!a && (type === "MCQ" ? a.selected_option_index != null : !!(a.answer_text && a.answer_text.trim()));

export function AssessmentRunner({
  assessmentId,
  applicationId,
  onSubmitted,
}: {
  assessmentId: string;
  applicationId: string;
  onSubmitted: () => void;
}) {
  const qc = useQueryClient();
  const overview = useQuery({
    queryKey: ["assessment-overview", assessmentId],
    queryFn: () => api.get(`/assessments/${assessmentId}/overview`).then((r) => r.data),
  });
  const existing = useQuery({
    queryKey: ["attempt-by-app", applicationId, assessmentId],
    queryFn: () => api.get(`/assessments/attempts/by-application/${applicationId}`, { params: { assessment_id: assessmentId } }).then((r) => r.data),
  });
  const attemptId: string | undefined = existing.data?.attempt?.id;
  const status: string | undefined = existing.data?.attempt?.status;

  const start = useMutation({
    mutationFn: () => api.post(`/assessments/${assessmentId}/attempts`, { application_id: applicationId }).then((r) => r.data),
    onSuccess: () => existing.refetch(),
  });

  const session = useQuery({
    queryKey: ["attempt-session", attemptId],
    enabled: !!attemptId && status === "IN_PROGRESS",
    refetchOnWindowFocus: false,
    staleTime: Infinity,
    queryFn: () =>
      api
        .get(`/assessments/attempts/${attemptId}`)
        .then((r) => ({ ...r.data, clockOffset: new Date(r.data.server_time).getTime() - Date.now() })),
  });

  const [idx, setIdx] = useState(0);
  const [answers, setAnswers] = useState<Record<string, Ans>>({});
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [confirming, setConfirming] = useState(false);
  const [remaining, setRemaining] = useState<number | null>(null);
  const timers = useRef<Record<string, number>>({});
  const autoSubmitted = useRef(false);

  const flat: any[] = (session.data?.sections ?? []).flatMap((s: any) =>
    s.questions.map((q: any) => ({ ...q, section: q.section ?? s.title }))
  );

  // Focus mode: hide the app navigation while a timed attempt is open.
  useEffect(() => {
    document.body.dataset.assessmentFocus = "1";
    return () => { delete document.body.dataset.assessmentFocus; };
  }, []);

  useEffect(() => {
    if (!session.data) return;
    const m: Record<string, Ans> = {};
    for (const q of flat) m[q.id] = q.answer;
    setAnswers(m);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.data]);

  const submit = useMutation({
    mutationFn: () => api.post(`/assessments/attempts/${attemptId}/submit`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["attempt-by-app", applicationId] });  // prefix: covers every stage of this application
      onSubmitted();
    },
  });
  const doSubmit = useCallback(() => {
    if (!submit.isPending && !submit.isSuccess) submit.mutate();
  }, [submit]);

  // Presentation only: the server's expires_at is authoritative and enforced on every write.
  useEffect(() => {
    if (!session.data?.expires_at) return;
    const end = new Date(session.data.expires_at).getTime();
    const tick = () => {
      const left = Math.max(0, Math.round((end - (Date.now() + session.data.clockOffset)) / 1000));
      setRemaining(left);
      if (left === 0 && !autoSubmitted.current) {
        autoSubmitted.current = true;
        doSubmit();
      }
    };
    tick();
    const t = window.setInterval(tick, 1000);
    return () => window.clearInterval(t);
  }, [session.data, doSubmit]);

  const save = useMutation({
    mutationFn: (p: {
      assessment_question_id: string;
      answer_text?: string;
      selected_option_index?: number;
      marked_for_review?: boolean;
    }) =>
      api
        .put(`/assessments/attempts/${attemptId}/answers`, p)
        .then((r) => ({ p, answer_id: r.data.answer_id as string })),
    onMutate: () => setSaveState("saving"),
    onSuccess: ({ p, answer_id }) => {
      setSaveState("saved");
      setAnswers((a) => ({ ...a, [p.assessment_question_id]: { ...a[p.assessment_question_id], answer_id } }));
    },
    onError: (e: any) => {
      setSaveState("error");
      if (e?.response?.data?.detail?.code === "ATTEMPT_EXPIRED" && !autoSubmitted.current) {
        autoSubmitted.current = true;
        doSubmit();
      }
    },
  });

  const patch = (id: string, p: Partial<Ans>) => setAnswers((a) => ({ ...a, [id]: { ...a[id], ...p } }));
  const autosave = (id: string, payload: any, delay = 800) => {
    window.clearTimeout(timers.current[id]);
    timers.current[id] = window.setTimeout(
      () => save.mutate({ assessment_question_id: id, ...payload }),
      delay
    );
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
      <div className="space-y-4" data-testid="assessment-completed">
        <div className="flex items-center gap-3 p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-emerald-950">
          <div className="w-8 h-8 rounded-full bg-emerald-100 flex items-center justify-center shrink-0">
            <svg className="w-5 h-5 text-emerald-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
          </div>
          <div>
            <p className="text-sm font-semibold">Assessment Successfully Submitted</p>
            <p className="text-xs text-emerald-800">
              Your responses are saved and securely scored. Results are shared with the recruiter.
            </p>
          </div>
        </div>
        <div className="border border-gray-200 rounded-lg divide-y divide-gray-100 bg-white">
          {(existing.data?.answers ?? []).map((a: any) => (
            <div key={a.answer_id} className="p-3 flex items-start justify-between gap-3 text-xs">
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <Badge tone="gray">{questionTypeLabel(a.question_type)}</Badge>
                  <span className="font-medium text-gray-800 line-clamp-1">{a.question_text}</span>
                </div>
                {a.coding && (
                  <p className="text-gray-500 font-mono">
                    Coding result:{" "}
                    {a.coding.status === "ALL_TESTS_PASSED"
                      ? "✓ All tests passed"
                      : a.coding.status === "SOME_TESTS_FAILED"
                      ? "✗ Some tests failed"
                      : "Error"}{" "}
                    ({a.coding.language})
                  </p>
                )}
              </div>
              <span className={`font-semibold shrink-0 ${a.completed ? "text-emerald-700" : "text-gray-400"}`}>
                {a.completed ? "Answered" : "Unanswered"}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  }

  if (!attemptId) {
    const o = overview.data;
    return (
      <div className="space-y-5" data-testid="assessment-intro">
        <div className="space-y-2">
          <h2 className="text-base font-bold text-gray-900">{o.title}</h2>
          <p className="text-xs text-gray-500">
            Please read the instructions carefully before launching your attempt.
          </p>
        </div>
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 p-4 bg-gray-50 rounded-xl border border-gray-200 text-xs">
          <div>
            <p className="text-gray-500">Total Questions</p>
            <p className="text-base font-semibold text-gray-900">{o.question_count} questions</p>
            <p className="text-[11px] text-gray-400 mt-0.5">
              {o.types.MCQ} MCQ · {o.types.TECHNICAL} Written · {o.types.CODING} Coding
            </p>
          </div>
          <div>
            <p className="text-gray-500">Time Limit</p>
            <p className="text-base font-semibold text-gray-900">{o.duration_minutes} minutes</p>
            <p className="text-[11px] text-gray-400 mt-0.5">Continuous server timer</p>
          </div>
          <div>
            <p className="text-gray-500">Integrity Check</p>
            <p className="text-base font-semibold text-gray-900">Proctored session</p>
            <p className="text-[11px] text-gray-400 mt-0.5">Autosaves each change</p>
          </div>
        </div>

        <ul className="text-xs text-gray-700 list-disc pl-5 space-y-1.5 leading-relaxed">
          <li>
            <strong>Server timer:</strong> The timer begins immediately when you click Start Assessment and cannot be paused or reset.
          </li>
          <li>
            <strong>Automatic save:</strong> All choices and code changes are synchronized in real-time.
          </li>
          <li>
            <strong>Flexible navigation:</strong> You may move back and forth between questions and flag questions for review.
          </li>
          <li>
            <strong>Auto-submit:</strong> When time expires, your current saved answers are automatically submitted.
          </li>
        </ul>

        <div className="pt-2">
          <Button onClick={() => start.mutate()} disabled={start.isPending}>
            {start.isPending ? "Starting…" : "Start Assessment"}
          </Button>
        </div>
        <ErrorBox error={start.error} />
      </div>
    );
  }

  if (session.isLoading || !session.data) return <Loading label="Loading assessment session…" />;
  if (session.error) return <ErrorBox error={session.error} onRetry={session.refetch} />;

  const current = flat[Math.min(idx, flat.length - 1)];
  const q = current.question;
  const a = answers[current.id];
  const counts = flat.reduce(
    (c, x) => {
      const ans = answers[x.id];
      return {
        answered: c.answered + (isAnswered(x.question.question_type, ans) ? 1 : 0),
        marked: c.marked + (ans?.marked_for_review ? 1 : 0),
      };
    },
    { answered: 0, marked: 0 }
  );
  const low = remaining != null && remaining <= 300;

  return (
    <div className="space-y-5" data-testid="assessment-active">
      {/* Focused Assessment Header Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm sticky top-2 z-20 space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs border-b border-gray-100 pb-3">
          <div className="space-y-0.5">
            <span className="font-semibold text-gray-900 block">{overview.data?.title ?? "Technical Assessment"}</span>
            <span className="text-gray-500">
              Answered {counts.answered} of {flat.length} questions · {counts.marked} marked for review
            </span>
          </div>

          <div className="flex items-center gap-3">
            <span className="text-[11px] font-medium text-gray-500">
              {saveState === "saving" ? (
                <span className="text-blue-600 flex items-center gap-1">
                  <svg className="animate-spin h-3 w-3" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z" />
                  </svg>
                  Saving…
                </span>
              ) : saveState === "saved" ? (
                <span className="text-emerald-700">✓ All changes saved</span>
              ) : saveState === "error" ? (
                <span className="text-red-600">Save failed — will retry</span>
              ) : null}
            </span>

            {/* Prominent Timer */}
            <div
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-mono text-sm font-bold shadow-xs ${
                low ? "bg-red-50 text-red-700 border border-red-200 animate-pulse" : "bg-gray-900 text-white"
              }`}
              data-testid="timer"
              aria-label="time remaining"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              <span>{remaining == null ? "--:--" : fmtClock(remaining)}</span>
            </div>
          </div>
        </div>

        {/* Progress bar */}
        <ProgressBar value={counts.answered} max={flat.length} />

        {/* Question Navigator */}
        <div className="space-y-1.5 pt-1">
          <div className="flex flex-wrap gap-1.5" data-testid="navigator">
            {flat.map((x, i) => {
              const ans = answers[x.id];
              const done = isAnswered(x.question.question_type, ans);
              const isMarked = ans?.marked_for_review;
              const isCurrent = i === idx;
              return (
                <button
                  key={x.id}
                  onClick={() => setIdx(i)}
                  title={`Question ${i + 1}: ${done ? "answered" : "unanswered"}${isMarked ? ", marked for review" : ""}`}
                  data-state={`${done ? "answered" : "unanswered"}${isMarked ? "+marked" : ""}`}
                  className={`w-8 h-8 text-xs font-semibold rounded-lg border transition-all ${
                    isCurrent ? "ring-2 ring-blue-600 ring-offset-1" : ""
                  } ${
                    isMarked
                      ? "border-amber-400 bg-amber-100 text-amber-900"
                      : done
                      ? "border-emerald-500 bg-emerald-50 text-emerald-800"
                      : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50"
                  }`}
                >
                  {i + 1}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-4 text-[11px] text-gray-500 pt-1">
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> Answered
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full bg-amber-400" /> Marked for review
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2.5 h-2.5 rounded-full border border-gray-300 bg-white" /> Unanswered
            </span>
          </div>
        </div>
      </div>

      {/* Main Question Workspace */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 shadow-sm space-y-4">
        <div className="flex items-center justify-between text-xs text-gray-500 border-b border-gray-100 pb-2">
          <span className="font-semibold text-gray-800">
            Question {idx + 1} of {flat.length} · {current.section}
          </span>
          <Badge tone="gray">{questionTypeLabel(q.question_type)}</Badge>
        </div>

        <p className="text-sm font-medium text-gray-900 whitespace-pre-wrap leading-relaxed">
          {q.question_text}
        </p>

        {/* Polished MCQ Selection Cards */}
        {q.question_type === "MCQ" && (
          <div className="space-y-2 pt-2" role="radiogroup" aria-label={`Answer options for question ${idx + 1}`}>
            {q.options?.map((opt: string, i: number) => {
              const selected = a?.selected_option_index === i;
              return (
                <label
                  key={`${current.id}-${i}`}
                  className={`flex items-start gap-3 p-3.5 rounded-xl border text-sm cursor-pointer transition ${
                    selected
                      ? "border-blue-600 bg-blue-50/60 text-blue-950 ring-1 ring-blue-600"
                      : "border-gray-200 hover:border-gray-300 hover:bg-gray-50/50 text-gray-800"
                  }`}
                >
                  <input
                    type="radio"
                    name={current.id}
                    className="mt-1 text-blue-600 focus:ring-blue-500"
                    checked={selected}
                    onChange={() => {
                      patch(current.id, { selected_option_index: i });
                      save.mutate({ assessment_question_id: current.id, selected_option_index: i });
                    }}
                  />
                  <span className="flex-1 leading-relaxed">{opt}</span>
                </label>
              );
            })}
          </div>
        )}

        {/* Technical Written with character count and clean autosave feedback */}
        {q.question_type === "TECHNICAL" && (
          <div className="space-y-2 pt-2">
            <textarea
              key={current.id}
              className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:border-blue-600 focus:ring-2 focus:ring-blue-100 focus:outline-none transition leading-relaxed"
              rows={8}
              defaultValue={a?.answer_text ?? ""}
              placeholder="Type your structured explanation or response here…"
              onChange={(e) => {
                const val = e.target.value;
                patch(current.id, { answer_text: val });
                autosave(current.id, { answer_text: val });
              }}
            />
            <div className="flex justify-between items-center text-xs text-gray-400">
              <span>Markdown and code formatting supported</span>
              <span>{(a?.answer_text ?? "").length} characters</span>
            </div>
          </div>
        )}

        {/* Coding Question with Monaco */}
        {q.question_type === "CODING" && (
          <CodingQuestion
            key={current.id}
            aqId={current.id}
            question={q}
            savedText={a?.answer_text}
            saveAndGetAnswerId={(text) => saveAndGetAnswerId(current.id, text)}
          />
        )}

        {/* Navigation & Review Controls */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-4 border-t border-gray-100">
          <div className="flex gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIdx((i) => Math.max(0, i - 1))}
              disabled={idx === 0}
            >
              ← Previous
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setIdx((i) => Math.min(flat.length - 1, i + 1))}
              disabled={idx >= flat.length - 1}
            >
              Next →
            </Button>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              const v = !a?.marked_for_review;
              patch(current.id, { marked_for_review: v });
              save.mutate({ assessment_question_id: current.id, marked_for_review: v });
            }}
          >
            {a?.marked_for_review ? "✓ Unmark Review" : "⚑ Mark for Review"}
          </Button>
        </div>
      </div>

      <ErrorBox error={submit.error} />

      {/* Submit Confirmation Card */}
      {!confirming ? (
        <div className="flex justify-end pt-2">
          <Button onClick={() => setConfirming(true)} disabled={submit.isPending}>
            Review and Submit Assessment
          </Button>
        </div>
      ) : (
        <div className="border border-amber-300 bg-amber-50/80 rounded-xl p-5 space-y-3 text-sm" data-testid="submit-confirm">
          <div>
            <h3 className="font-bold text-amber-950">Ready to submit your assessment?</h3>
            <p className="text-xs text-amber-800 mt-1">
              You have answered <b>{counts.answered}</b> of {flat.length} questions.{" "}
              <b>{flat.length - counts.answered}</b> remain unanswered. <b>{counts.marked}</b> marked for review.
            </p>
            <p className="text-xs text-gray-600 mt-0.5">
              Once submitted, you will not be able to revisit or modify your responses.
            </p>
          </div>
          <div className="flex gap-2 pt-1">
            <Button onClick={doSubmit} disabled={submit.isPending}>
              {submit.isPending ? "Submitting…" : "Confirm & Submit"}
            </Button>
            <Button variant="secondary" onClick={() => setConfirming(false)} disabled={submit.isPending}>
              Keep Working
            </Button>
          </div>
        </div>
      )}

      {save.error && !(save.error as any)?.response?.data?.detail?.code && (
        <p className="text-xs text-red-600">{apiError(save.error)}</p>
      )}
    </div>
  );
}
