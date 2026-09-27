import Editor from "@monaco-editor/react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

export function AssessmentRunner({ assessmentId, applicationId }: { assessmentId: string; applicationId: string }) {
  const qc = useQueryClient();
  const { data: detail } = useQuery({
    queryKey: ["assessment-detail", assessmentId],
    queryFn: () => api.get(`/assessments/${assessmentId}`).then((r) => r.data),
  });

  const [attemptId, setAttemptId] = useState<string | null>(null);
  const [codeByQuestion, setCodeByQuestion] = useState<Record<string, string>>({});
  const [codingResults, setCodingResults] = useState<Record<string, any>>({});

  const startAttempt = useMutation({
    mutationFn: () => api.post(`/assessments/${assessmentId}/attempts`, { application_id: applicationId }),
    onSuccess: (res) => setAttemptId(res.data.id),
  });

  const saveAnswer = useMutation({
    mutationFn: (payload: { assessment_question_id: string; answer_text?: string; selected_option_index?: number }) =>
      api.put(`/assessments/attempts/${attemptId}/answers`, payload),
  });

  const submitCode = useMutation({
    mutationFn: (payload: { assessment_answer_id?: string; question_id: string; language: string; source_code: string }) =>
      api.post("/coding/submit", payload),
  });

  const submitAttempt = useMutation({
    mutationFn: () => api.post(`/assessments/attempts/${attemptId}/submit`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications-mine"] }),
  });

  if (!detail) return null;

  if (!attemptId) {
    return (
      <button onClick={() => startAttempt.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
        {startAttempt.isPending ? "Starting..." : "Start assessment"}
      </button>
    );
  }

  return (
    <div className="space-y-6">
      {detail.sections.map((section: any) => (
        <div key={section.id}>
          <h3 className="text-sm font-medium text-gray-800 mb-2">{section.title}</h3>
          <div className="space-y-4">
            {section.questions.map((aq: any) => {
              const q = aq.question;
              return (
                <div key={aq.id} className="border border-gray-200 rounded-md p-3">
                  <p className="text-sm text-gray-800 mb-2">{q.question_text}</p>
                  {q.question_type === "MCQ" && (
                    <div className="space-y-1">
                      {q.options?.map((opt: string, idx: number) => (
                        <label key={idx} className="flex items-center gap-2 text-sm text-gray-600">
                          <input
                            type="radio"
                            name={aq.id}
                            onChange={() =>
                              saveAnswer.mutate({ assessment_question_id: aq.id, selected_option_index: idx })
                            }
                          />
                          {opt}
                        </label>
                      ))}
                    </div>
                  )}
                  {q.question_type === "TECHNICAL" && (
                    <textarea
                      className="w-full border border-gray-300 rounded-md p-2 text-sm"
                      rows={4}
                      placeholder="Your answer..."
                      onBlur={(e) =>
                        saveAnswer.mutate({ assessment_question_id: aq.id, answer_text: e.target.value })
                      }
                    />
                  )}
                  {q.question_type === "CODING" && (
                    <div className="space-y-2">
                      <Editor
                        height="220px"
                        defaultLanguage="python"
                        defaultValue={q.starter_code ?? "def solve():\n    pass\n"}
                        onChange={(val) => setCodeByQuestion((prev) => ({ ...prev, [aq.id]: val ?? "" }))}
                      />
                      <button
                        className="text-xs bg-gray-800 text-white px-3 py-1.5 rounded-md"
                        onClick={() =>
                          submitCode.mutate(
                            {
                              question_id: q.id,
                              language: "python",
                              source_code: codeByQuestion[aq.id] ?? q.starter_code ?? "",
                            },
                            { onSuccess: (res) => setCodingResults((prev) => ({ ...prev, [aq.id]: res.data })) }
                          )
                        }
                      >
                        Run tests
                      </button>
                      {codingResults[aq.id] && (
                        <p className="text-xs text-gray-600">
                          {codingResults[aq.id].passed_count}/{codingResults[aq.id].total_count} tests passed
                        </p>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      ))}
      <button
        onClick={() => submitAttempt.mutate()}
        className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
      >
        {submitAttempt.isPending ? "Submitting..." : "Submit assessment"}
      </button>
      {submitAttempt.data && (
        <p className="text-sm text-gray-700">
          Score: {Math.round(submitAttempt.data.data.total_score * 100)}%
        </p>
      )}
    </div>
  );
}
