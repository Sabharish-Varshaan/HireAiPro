import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

export default function JobsFeedPage() {
  const { data: jobs, isLoading } = useQuery({
    queryKey: ["jobs", "PUBLISHED"],
    queryFn: () => api.get("/jobs", { params: { status: "PUBLISHED" } }).then((r) => r.data),
  });

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">Open roles</h1>
      {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {jobs?.length === 0 && <p className="text-sm text-gray-500">No published roles yet.</p>}
      <div className="space-y-3">
        {jobs?.map((job: any) => (
          <Link
            key={job.id}
            to={`/student/jobs/${job.id}`}
            className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-300"
          >
            <p className="font-medium text-gray-900">{job.title}</p>
            <p className="text-sm text-gray-500">{[job.organization_name, job.location, job.employment_type].filter(Boolean).join(" · ")}</p>
          </Link>
        ))}
      </div>
    </div>
  );
}
