import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

export function InterviewRunner({ interviewId }: { interviewId: string }) {
  const qc = useQueryClient();
  const [answer, setAnswer] = useState("");

  const { data: turns } = useQuery({
    queryKey: ["interview-turns", interviewId],
    queryFn: () => api.get(`/interviews/${interviewId}/turns`).then((r) => r.data),
  });

  const nextTurn = useMutation({
    mutationFn: () => api.post(`/interviews/${interviewId}/next-turn`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] }),
  });

  const answerTurn = useMutation({
    mutationFn: (turnId: string) => api.post(`/interviews/turns/${turnId}/answer`, { answer_text: answer }),
    onSuccess: () => {
      setAnswer("");
      qc.invalidateQueries({ queryKey: ["interview-turns", interviewId] });
    },
  });

  const currentTurn = turns?.[turns.length - 1];
  const currentAnswered = currentTurn?.student_answer_text != null;

  return (
    <div className="space-y-4">
      {turns?.map((t: any) => (
        <div key={t.id} className="border border-gray-200 rounded-md p-3">
          <p className="text-xs text-gray-400 mb-1">Question {t.turn_index + 1} · {t.difficulty}</p>
          <p className="text-sm text-gray-800">{t.question_text}</p>
          {t.student_answer_text && (
            <p className="text-sm text-gray-500 mt-2 border-t border-gray-100 pt-2">{t.student_answer_text}</p>
          )}
        </div>
      ))}

      {currentTurn && !currentAnswered && (
        <div className="space-y-2">
          <textarea
            className="w-full border border-gray-300 rounded-md p-2 text-sm"
            rows={4}
            value={answer}
            onChange={(e) => setAnswer(e.target.value)}
            placeholder="Type your answer..."
          />
          <button
            onClick={() => answerTurn.mutate(currentTurn.id)}
            className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
          >
            {answerTurn.isPending ? "Submitting..." : "Submit answer"}
          </button>
        </div>
      )}

      {(!currentTurn || currentAnswered) && (
        <button
          onClick={() => nextTurn.mutate()}
          className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
        >
          {nextTurn.isPending ? "Loading..." : turns?.length ? "Next question" : "Begin interview"}
        </button>
      )}
    </div>
  );
}
