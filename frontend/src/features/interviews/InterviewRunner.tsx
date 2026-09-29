import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading, apiError } from "../../components/ui";
import { useSpokenQuestion } from "./useSpokenQuestion";

function useRecorder(shared?: MediaStream | null) {
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const [state, setState] = useState<"idle" | "recording">("idle");
  const [error, setError] = useState<string | null>(null);
  const start = async () => {
    setError(null);
    try {
      // reuse the proctored session's microphone instead of acquiring a second one
      const stream = shared?.getAudioTracks().length
        ? new MediaStream(shared.getAudioTracks())
        : await navigator.mediaDevices.getUserMedia({ audio: true });
      const mime = MediaRecorder.isTypeSupported("audio/webm") ? "audio/webm" : "";
      const r = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined);
      chunks.current = [];
      r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
      r.start();
      rec.current = r;
      setState("recording");
    } catch (e) {
      setError(`Microphone unavailable (${(e as Error).message}). You can type your answer instead.`);
    }
  };
  const stop = () =>
    new Promise<Blob>((resolve) => {
      const r = rec.current!;
      r.onstop = () => {
        if (!shared) r.stream.getTracks().forEach((t) => t.stop());
        setState("idle");
        resolve(new Blob(chunks.current, { type: r.mimeType || "audio/webm" }));
      };
      r.stop();
    });
  return { state, error, start, stop };
}

export function InterviewRunner({
  interviewId,
  mediaStream,
  onCompleted,
}: {
  interviewId: string;
  mediaStream?: MediaStream | null;
  onCompleted?: () => void;
}) {
  const qc = useQueryClient();
  const [answer, setAnswer] = useState("");
  const [source, setSource] = useState<"text" | "voice">("text");
  const [transcript, setTranscript] = useState<any>(null);
  const [showHistory, setShowHistory] = useState(false);
  const recorder = useRecorder(mediaStream);

  const turns = useQuery({
    queryKey: ["interview-turns", interviewId],
    queryFn: () => api.get(`/interviews/${interviewId}/turns`).then((r) => r.data),
  });
  const nextTurn = useMutation({
    mutationFn: () => api.post(`/interviews/${interviewId}/next-turn`).then((r) => r.data),
    onSuccess: (d) => {
      if (d === null) onCompleted?.();
      qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] });
      qc.invalidateQueries({ queryKey: ["interview"] });
      qc.invalidateQueries({ queryKey: ["application"] });
    },
  });
  const answerTurn = useMutation({
    mutationFn: (turnId: string) =>
      api.post(`/interviews/turns/${turnId}/answer`, { answer_text: answer, answer_source: source }),
    onSuccess: async () => {
      setAnswer("");
      setSource("text");
      setTranscript(null);
      await qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] });
      nextTurn.mutate(); // the next question comes from the prepared pool: advance without another click
    },
  });
  const transcribe = useMutation({
    mutationFn: async ({ turnId, blob }: { turnId: string; blob: Blob }) => {
      const fd = new FormData();
      fd.append("audio", blob, blob.type.includes("webm") ? "answer.webm" : "answer.wav");
      return (await api.post(`/interviews/turns/${turnId}/transcribe`, fd)).data;
    },
    onSuccess: (r) => {
      setTranscript(r);
      setAnswer(r.text);
      setSource("voice");
    },
  });
  const finish = useMutation({
    mutationFn: () => api.post(`/interviews/${interviewId}/finish`),
    onSuccess: () => {
      onCompleted?.();
      qc.invalidateQueries({ queryKey: ["interview"] });
      qc.invalidateQueries({ queryKey: ["application"] });
    },
  });

  const list: any[] = turns.data ?? [];
  const began = useRef(false);
  useEffect(() => {
    // question 1 is prepared before Start: show it as soon as the runner mounts
    if (turns.data && turns.data.length === 0 && !began.current && !nextTurn.isPending) {
      began.current = true;
      nextTurn.mutate();
    }
  }, [turns.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const current = list[list.length - 1];
  const pending = current && !current.student_answer_text;
  const completedByAgent = nextTurn.isSuccess && nextTurn.data === null;
  const voice = useSpokenQuestion(pending ? current.id : undefined, pending ? current.question_text : undefined);

  if (turns.isLoading) return <Loading label="Loading interview session…" />;

  const previousTurns = list.slice(0, pending ? list.length - 1 : list.length);

  return (
    <div className="space-y-5">
      {/* Collapsed Previous Turns Header */}
      {previousTurns.length > 0 && (
        <div className="border border-gray-200 rounded-xl overflow-hidden bg-gray-50/50">
          <button
            type="button"
            onClick={() => setShowHistory((v) => !v)}
            className="w-full flex items-center justify-between p-3.5 text-xs font-semibold text-gray-700 hover:bg-gray-100/60 transition"
          >
            <span>
              Previous Questions ({previousTurns.length} completed)
            </span>
            <span className="text-blue-600 font-medium">
              {showHistory ? "Hide transcript ▲" : "View transcript ▼"}
            </span>
          </button>
          {showHistory && (
            <div className="divide-y divide-gray-200 border-t border-gray-200 p-3 space-y-3 bg-white">
              {previousTurns.map((t) => (
                <div key={t.id} className="pt-2 first:pt-0 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between text-gray-500">
                    <span className="font-semibold text-gray-800">
                      Question {t.turn_index + 1} · {t.skill_name}
                    </span>
                    <Badge tone="gray">{t.answer_source ?? "text"}</Badge>
                  </div>
                  <p className="text-gray-900 font-medium">{t.question_text}</p>
                  {t.student_answer_text && (
                    <div className="p-2.5 bg-gray-50 rounded border border-gray-100 text-gray-700 italic">
                      “{t.student_answer_text}”
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Active Question Focus Card */}
      {current && pending && (
        <div className="border-2 border-blue-600 bg-white rounded-xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between text-xs border-b border-gray-100 pb-2.5">
            <span className="font-bold text-blue-900 uppercase tracking-wider text-[11px]">
              Active Question {current.turn_index + 1}
            </span>
            <Badge tone="blue">{current.skill_name}</Badge>
          </div>

          <p className="text-base font-semibold text-gray-950 leading-relaxed">
            {current.question_text}
          </p>

          {/* Voice Controls with professional SVGs */}
          {voice.supported && (
            <div className="flex items-center gap-2 pt-1" data-testid="voice-controls">
              <Button
                variant="secondary"
                size="sm"
                onClick={voice.replay}
                icon={
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.536 8.464a5 5 0 010 7.072m2.828-9.9a9 9 0 010 12.728M5.586 15H4a1 1 0 01-1-1v-4a1 1 0 011-1h1.586l4.707-4.707C10.923 3.663 12 4.109 12 5v14c0 .891-1.077 1.337-1.707.707L5.586 15z" />
                  </svg>
                }
              >
                Replay Audio
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={voice.toggleMute}
              >
                {voice.enabled ? "Mute audio" : "Unmute audio"}
              </Button>
              {voice.speaking && (
                <span className="text-xs text-blue-700 animate-pulse flex items-center gap-1">
                  Speaking question…
                </span>
              )}
            </div>
          )}

          {/* Response Input Section */}
          <div className="space-y-3 pt-3 border-t border-gray-100">
            <div className="flex flex-wrap items-center gap-3">
              {recorder.state === "idle" ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={recorder.start}
                  disabled={transcribe.isPending}
                  icon={
                    <svg className="w-3.5 h-3.5 text-blue-700" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M19 11a7 7 0 01-7 7m0 0a7 7 0 01-7-7m7 7v4m0 0H8m4 0h4m-4-8a3 3 0 01-3-3V5a3 3 0 116 0v6a3 3 0 01-3 3z" />
                    </svg>
                  }
                >
                  Record Voice Response
                </Button>
              ) : (
                <Button
                  variant="danger"
                  size="sm"
                  onClick={async () => transcribe.mutate({ turnId: current.id, blob: await recorder.stop() })}
                  icon={
                    <span className="w-2.5 h-2.5 rounded-xs bg-red-600 shrink-0" />
                  }
                >
                  Stop Recording
                </Button>
              )}

              {recorder.state === "recording" && (
                <span className="text-xs text-red-600 font-semibold animate-pulse flex items-center gap-1.5">
                  <span className="w-2 h-2 rounded-full bg-red-600" /> Recording audio…
                </span>
              )}

              {transcribe.isPending && (
                <span className="text-xs text-amber-700 font-medium">
                  Processing your response…
                </span>
              )}

              {transcript && (
                <span className="text-xs text-emerald-700 font-medium">
                  ✓ Response saved ({transcript.duration_seconds}s) — edit text below if needed
                </span>
              )}
            </div>

            {recorder.error && <p className="text-xs text-red-600">{recorder.error}</p>}
            {transcribe.error && <p className="text-xs text-red-600">{apiError(transcribe.error)}</p>}

            <textarea
              className="w-full border border-gray-300 rounded-xl p-3 text-sm focus:border-blue-600 focus:ring-2 focus:ring-blue-100 focus:outline-none transition leading-relaxed"
              rows={4}
              value={answer}
              onChange={(e) => setAnswer(e.target.value)}
              placeholder="Speak using the button above or type your structured response here…"
            />

            <div className="flex justify-end pt-1">
              <Button
                onClick={() => {
                  voice.cancel();
                  answerTurn.mutate(current.id);
                }}
                disabled={answerTurn.isPending || !answer.trim()}
              >
                {answerTurn.isPending ? "Submitting response…" : "Submit Response"}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Dynamic Status Notification */}
      {(answerTurn.isPending || (answerTurn.isSuccess && nextTurn.isPending)) && (
        <div className="p-4 bg-blue-50 border border-blue-200 rounded-xl flex items-center gap-3 text-xs text-blue-900" role="status" data-testid="interview-status">
          <svg className="animate-spin h-4 w-4 text-blue-700 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z" />
          </svg>
          <span>
            {answerTurn.isPending
              ? "Response saved. Evaluating your response…"
              : "Preparing next question…"}
          </span>
        </div>
      )}

      {list.length === 0 && nextTurn.isPending && (
        <div className="p-4 bg-gray-50 border border-gray-200 rounded-xl text-xs text-gray-700" role="status">
          Preparing your first question…
        </div>
      )}

      {!pending && !completedByAgent && !nextTurn.isPending && !answerTurn.isPending && (
        <div className="flex gap-2">
          <Button onClick={() => nextTurn.mutate()} disabled={nextTurn.isPending}>
            {nextTurn.isPending
              ? "Preparing next question…"
              : list.length
              ? "Next Question"
              : "Begin Interview"}
          </Button>
          {list.some((t) => t.student_answer_text) && (
            <Button variant="secondary" onClick={() => finish.mutate()} disabled={finish.isPending}>
              Finish Interview
            </Button>
          )}
        </div>
      )}

      {completedByAgent && (
        <div className="p-4 bg-emerald-50 border border-emerald-200 rounded-xl text-xs text-emerald-950 font-medium">
          ✓ The interview has gathered sufficient evidence across required competencies — session completed.
        </div>
      )}

      <ErrorBox error={nextTurn.error || answerTurn.error || finish.error} />
    </div>
  );
}
