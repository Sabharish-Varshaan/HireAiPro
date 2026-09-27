import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

export default function ApplicationsPage() {
  const { data: applications } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">My applications</h1>
      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        {(applications ?? []).length === 0 && (
          <p className="p-4 text-sm text-gray-500">You haven't applied to anything yet.</p>
        )}
        {applications?.map((a: any) => (
          <div key={a.id} className="p-4 flex items-center justify-between text-sm">
            <span className="text-gray-700">Job {a.job_id.slice(0, 8)}</span>
            <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-700">{a.status}</span>
            <Link className="underline text-gray-900" to={`/student/applications/${a.id}`}>
              Open
            </Link>
          </div>
        ))}
      </div>
    </div>
  );
}
