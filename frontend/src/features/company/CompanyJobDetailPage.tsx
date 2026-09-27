import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";

export default function CompanyJobDetailPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const [jdText, setJdText] = useState("");

  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data),
    refetchInterval: 4000,
  });

  const { data: assessment } = useQuery({
    queryKey: ["assessment-by-job", jobId],
    queryFn: () => api.get(`/assessments/by-job/${jobId}`).then((r) => r.data),
    enabled: job?.status !== "DRAFT" && job?.status !== "SKILLS_EXTRACTED",
  });

  const { data: candidates } = useQuery({
    queryKey: ["ranked", jobId],
    queryFn: () => api.get(`/matching/jobs/${jobId}/ranked`).then((r) => r.data),
    enabled: !!assessment,
  });

  const processJd = useMutation({
    mutationFn: async () => {
      await api.post(`/jobs/${jobId}/jd-file`, (() => {
        const fd = new FormData();
        fd.append("file", new Blob([jdText], { type: "text/plain" }), "jd.txt");
        return fd;
      })(), { headers: { "Content-Type": "multipart/form-data" } });
      return api.post(`/jobs/${jobId}/process`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });

  const [editedSkills, setEditedSkills] = useState<any[] | null>(null);
  const skills = editedSkills ?? job?.skills ?? [];

  const confirmRequirements = useMutation({
    mutationFn: () =>
      api.put(`/jobs/${jobId}/requirements/confirm`, {
        skills: skills.map((s: any) => ({
          id: s.id,
          skill_id: s.skill_id,
          raw_skill_name: s.raw_skill_name,
          requirement_type: s.requirement_type,
          minimum_level: s.minimum_level,
          importance: s.importance,
          delete: false,
        })),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });

  const generateAssessment = useMutation({
    mutationFn: () => api.post(`/assessments/jobs/${jobId}/generate`, { title: `${job.title} Assessment` }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assessment-by-job", jobId] }),
  });

  const publishAssessment = useMutation({
    mutationFn: () => api.post(`/assessments/${assessment.id}/publish`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", jobId] }),
  });

  if (!job) return null;

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">{job.title}</h1>
        <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600">{job.status}</span>
      </div>

      {job.status === "DRAFT" && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
          <h2 className="text-sm font-semibold text-gray-700">Paste job description</h2>
          <textarea
            className="w-full border border-gray-300 rounded-md p-2 text-sm"
            rows={8}
            value={jdText}
            onChange={(e) => setJdText(e.target.value)}
          />
          <button
            onClick={() => processJd.mutate()}
            className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
          >
            {processJd.isPending ? "Processing..." : "Analyze with AI"}
          </button>
        </div>
      )}

      {job.status === "SKILLS_EXTRACTED" && (
        <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
          <h2 className="text-sm font-semibold text-gray-700">Review AI-extracted requirements</h2>
          {skills.map((s: any, idx: number) => (
            <div key={s.id} className="grid grid-cols-5 gap-2 items-center text-sm border-b border-gray-100 pb-2">
              <span className="col-span-2 text-gray-800">{s.raw_skill_name}</span>
              <select
                className="border border-gray-300 rounded px-1 py-1 text-xs"
                value={s.requirement_type}
                onChange={(e) => {
                  const copy = [...skills];
                  copy[idx] = { ...s, requirement_type: e.target.value };
                  setEditedSkills(copy);
                }}
              >
                <option value="required">required</option>
                <option value="preferred">preferred</option>
              </select>
              <span className="text-xs text-gray-500">min level {s.minimum_level}</span>
              <span className="text-xs text-gray-400">confidence {Math.round(s.extraction_confidence * 100)}%</span>
            </div>
          ))}
          <button
            onClick={() => confirmRequirements.mutate()}
            className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
          >
            {confirmRequirements.isPending ? "Confirming..." : "Confirm requirements"}
          </button>
        </div>
      )}

      {job.status === "REQUIREMENTS_CONFIRMED" && (
        <button onClick={() => generateAssessment.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
          {generateAssessment.isPending ? "Generating (this can take a few minutes)..." : "Generate assessment"}
        </button>
      )}

      {assessment && assessment.status !== "PUBLISHED" && (
        <button onClick={() => publishAssessment.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
          Publish assessment
        </button>
      )}

      {candidates && candidates.length > 0 && (
        <div className="bg-white border border-gray-200 rounded-lg divide-y">
          <h2 className="text-sm font-semibold text-gray-700 p-4 pb-0">Ranked candidates</h2>
          {candidates.map((c: any) => (
            <div key={c.id} className="p-4 flex items-center justify-between text-sm">
              <span className="text-gray-700">{c.student_id.slice(0, 8)}</span>
              <span className="font-medium">{Math.round(c.match_score * 100)}%</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
