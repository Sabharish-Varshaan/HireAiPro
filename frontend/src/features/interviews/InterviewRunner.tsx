import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading, apiError, pct } from "../../components/ui";

function useRecorder() {
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const [state, setState] = useState<"idle" | "recording">("idle");
  const [error, setError] = useState<string | null>(null);
  const start = async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
  const stop = () => new Promise<Blob>((resolve) => {
    const r = rec.current!;
    r.onstop = () => { r.stream.getTracks().forEach((t) => t.stop()); setState("idle"); resolve(new Blob(chunks.current, { type: r.mimeType || "audio/webm" })); };
    r.stop();
  });
  return { state, error, start, stop };
}

export function InterviewRunner({ interviewId }: { interviewId: string }) {
  const qc = useQueryClient();
  const [answer, setAnswer] = useState("");
  const [source, setSource] = useState<"text" | "voice">("text");
  const [transcript, setTranscript] = useState<any>(null);
  const recorder = useRecorder();

  const turns = useQuery({ queryKey: ["interview-turns", interviewId], queryFn: () => api.get(`/interviews/${interviewId}/turns`).then((r) => r.data) });
  const nextTurn = useMutation({
    mutationFn: () => api.post(`/interviews/${interviewId}/next-turn`).then((r) => r.data),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] }); qc.invalidateQueries({ queryKey: ["interview"] }); qc.invalidateQueries({ queryKey: ["application"] }); },
  });
  const answerTurn = useMutation({
    mutationFn: (turnId: string) => api.post(`/interviews/turns/${turnId}/answer`, { answer_text: answer, answer_source: source }),
    onSuccess: () => { setAnswer(""); setSource("text"); setTranscript(null); qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] }); },
  });
  const transcribe = useMutation({
    mutationFn: async ({ turnId, blob }: { turnId: string; blob: Blob }) => {
      const fd = new FormData();
      fd.append("audio", blob, blob.type.includes("webm") ? "answer.webm" : "answer.wav");
      return (await api.post(`/interviews/turns/${turnId}/transcribe`, fd)).data;
    },
    onSuccess: (r) => { setTranscript(r); setAnswer(r.text); setSource("voice"); },
  });
  const finish = useMutation({
    mutationFn: () => api.post(`/interviews/${interviewId}/finish`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["interview"] }); qc.invalidateQueries({ queryKey: ["application"] }); },
  });

  if (turns.isLoading) return <Loading />;
  const list: any[] = turns.data ?? [];
  const current = list[list.length - 1];
  const pending = current && !current.student_answer_text;
  const completedByAgent = nextTurn.isSuccess && nextTurn.data === null;

  return (
    <div className="space-y-4">
      {list.map((t) => (
        <div key={t.id} className="border border-gray-200 rounded-md p-3 space-y-1">
          <p className="text-xs text-gray-500">Question {t.turn_index + 1} · {t.skill_name} · <Badge tone="gray">{t.difficulty}</Badge></p>
          <p className="text-sm text-gray-900">{t.question_text}</p>
          {t.student_answer_text && (
            <div className="text-sm text-gray-600 border-t border-gray-100 pt-2">
              <p>{t.student_answer_text} <span className="text-xs text-gray-400">({t.answer_source})</span></p>
              {t.rubric_evaluation && <p className="text-xs text-gray-500">Rubric: accuracy {pct(t.rubric_evaluation.concept_accuracy)}, reasoning {pct(t.rubric_evaluation.reasoning)}, completeness {pct(t.rubric_evaluation.completeness)}</p>}
            </div>
          )}
        </div>
      ))}

      {pending && (
        <div className="space-y-2">
          <div className="flex items-center gap-2">
            {recorder.state === "idle" ? (
              <Button variant="secondary" onClick={recorder.start} disabled={transcribe.isPending}>🎙 Start recording</Button>
            ) : (
              <Button variant="danger" onClick={async () => transcribe.mutate({ turnId: current.id, blob: await recorder.stop() })}>■ Stop recording</Button>
            )}
            {recorder.state === "recording" && <span className="text-xs text-red-600">Recording…</span>}
            {transcribe.isPending && <span className="text-xs text-amber-700">Transcribing with faster-whisper…</span>}
            {transcript && <span className="text-xs text-gray-500">Transcribed {transcript.duration_seconds}s ({transcript.model}, {transcript.language}) — edit below if needed</span>}
          </div>
          {recorder.error && <p className="text-xs text-red-600">{recorder.error}</p>}
          {transcribe.error && <p className="text-xs text-red-600">{apiError(transcribe.error)}</p>}
          <textarea className="w-full border border-gray-300 rounded-md p-2 text-sm" rows={4} value={answer}
            onChange={(e) => setAnswer(e.target.value)} placeholder="Type your answer, or record it above…" />
          <Button onClick={() => answerTurn.mutate(current.id)} disabled={answerTurn.isPending || !answer.trim()}>
            {answerTurn.isPending ? "Scoring…" : "Submit answer"}
          </Button>
        </div>
      )}

      {!pending && !completedByAgent && (
        <div className="flex gap-2">
          <Button onClick={() => nextTurn.mutate()} disabled={nextTurn.isPending}>
            {nextTurn.isPending ? "Interviewer is choosing the next question…" : list.length ? "Next question" : "Begin interview"}
          </Button>
          {list.some((t) => t.student_answer_text) && <Button variant="secondary" onClick={() => finish.mutate()} disabled={finish.isPending}>Finish interview</Button>}
        </div>
      )}
      {completedByAgent && <p className="text-sm text-green-700">The interviewer has enough evidence — interview complete.</p>}
      <ErrorBox error={nextTurn.error || answerTurn.error || finish.error} />
    </div>
  );
}
