import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";

export default function JobDetailPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const { data: job } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data),
  });
  const { data: applications } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });
  const applied = applications?.some((a: any) => a.job_id === jobId);

  const apply = useMutation({
    mutationFn: () => api.post("/applications", { job_id: jobId }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["applications-mine"] }),
  });

  if (!job) return null;

  return (
    <div className="max-w-2xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">{job.title}</h1>
      <p className="text-sm text-gray-600 whitespace-pre-wrap">{job.description_raw}</p>

      <h2 className="text-sm font-semibold text-gray-700 mt-4">Required skills</h2>
      <div className="flex flex-wrap gap-2">
        {job.skills?.map((s: any) => (
          <span
            key={s.id}
            className={`text-xs px-2 py-1 rounded-full border ${
              s.requirement_type === "required" ? "border-gray-400 text-gray-700" : "border-gray-200 text-gray-500"
            }`}
          >
            {s.raw_skill_name}
          </span>
        ))}
      </div>

      <button
        disabled={applied || apply.isPending}
        onClick={() => apply.mutate()}
        className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md disabled:opacity-50"
      >
        {applied ? "Applied" : apply.isPending ? "Applying..." : "Apply"}
      </button>
    </div>
  );
}
