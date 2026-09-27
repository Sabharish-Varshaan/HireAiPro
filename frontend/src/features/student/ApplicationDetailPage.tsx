import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { AssessmentRunner } from "../assessments/AssessmentRunner";
import { InterviewRunner } from "../interviews/InterviewRunner";

export default function ApplicationDetailPage() {
  const { applicationId } = useParams();

  const { data: applications } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });
  const application = applications?.find((a: any) => a.id === applicationId);

  const { data: assessment } = useQuery({
    queryKey: ["assessment-by-job", application?.job_id],
    queryFn: () => api.get(`/assessments/by-job/${application.job_id}`).then((r) => r.data),
    enabled: !!application?.job_id,
  });

  const { data: match } = useQuery({
    queryKey: ["match", applicationId],
    queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data).catch(() => null),
    enabled: !!applicationId,
    retry: false,
  });

  const startInterview = useMutation({
    mutationFn: () => api.post("/interviews/start", { application_id: applicationId }),
  });

  if (!application) return <p className="text-sm text-gray-500">Loading...</p>;

  return (
    <div className="max-w-3xl space-y-6">
      <div>
        <h1 className="text-lg font-semibold text-gray-900">Application status</h1>
        <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700">{application.status}</span>
      </div>

      {assessment && (
        <section className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Assessment: {assessment.title}</h2>
          <AssessmentRunner assessmentId={assessment.id} applicationId={applicationId!} />
        </section>
      )}

      {application.status === "ASSESSMENT_COMPLETED" && (
        <section className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Adaptive interview</h2>
          {!startInterview.data ? (
            <button
              onClick={() => startInterview.mutate()}
              className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md"
            >
              Start interview
            </button>
          ) : (
            <InterviewRunner interviewId={startInterview.data.data.id} />
          )}
        </section>
      )}

      {match && (
        <section className="bg-white border border-gray-200 rounded-lg p-4">
          <h2 className="text-sm font-semibold text-gray-700 mb-3">Your match</h2>
          <p className="text-2xl font-semibold text-gray-900">{Math.round(match.match_score * 100)}%</p>
          <div className="grid grid-cols-2 gap-2 mt-3 text-xs text-gray-600">
            <p>Required fit: {Math.round(match.required_skill_fit * 100)}%</p>
            <p>Preferred fit: {Math.round(match.preferred_skill_fit * 100)}%</p>
          </div>
          {match.missing_skills?.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-medium text-gray-700">Skill gaps</p>
              <ul className="text-xs text-gray-500 list-disc pl-4">
                {match.missing_skills.map((s: any) => (
                  <li key={s.skill_id}>{s.skill_name || s.skill_id}</li>
                ))}
              </ul>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
