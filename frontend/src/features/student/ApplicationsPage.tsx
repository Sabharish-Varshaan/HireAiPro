import { pendingAction } from "../../lib/pipeline";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import {
  Badge,
  Button,
  Card,
  Empty,
  PageHeader,
  SkeletonCard,
} from "../../components/ui";

export default function ApplicationsPage() {
  const { data: applications, isLoading } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="My Applications"
        description="Track the status, assessments, and next steps for your job applications."
        actions={
          <Link to="/student/jobs">
            <Button size="sm">Browse More Roles</Button>
          </Link>
        }
      />

      {isLoading ? (
        <div className="space-y-3">
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : (applications ?? []).length === 0 ? (
        <Card>
          <Empty
            action={
              <Link to="/student/jobs">
                <Button size="sm">Explore Available Roles</Button>
              </Link>
            }
          >
            You haven't submitted any job applications yet.
          </Empty>
        </Card>
      ) : (
        <div className="space-y-3">
          {applications.map((a: any) => (
            <div
              key={a.id}
              className="bg-white border border-gray-200 rounded-xl p-5 hover:border-blue-400 hover:shadow-sm transition flex flex-col sm:flex-row sm:items-center justify-between gap-4"
            >
              <div className="space-y-1">
                <div className="flex items-center gap-2.5">
                  <h2 className="text-base font-semibold text-gray-900">{a.job_title}</h2>
                  <Badge>{a.status}</Badge>
                </div>
                <p className="text-xs text-gray-500 font-medium">{a.organization_name}</p>
                {pendingAction(a) && (
                  <p className="text-xs font-medium text-blue-700" data-testid="pending-action">
                    {pendingAction(a)}
                    {a.stages_total ? <span className="text-gray-400 font-normal"> · {a.stages_done} of {a.stages_total} steps done</span> : null}
                  </p>
                )}
                {a.applied_at && (
                  <p className="text-xs text-gray-400">
                    Applied on {new Date(a.applied_at).toLocaleDateString()}
                  </p>
                )}
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <Link
                  className="inline-flex items-center text-xs font-semibold px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 transition"
                  to={`/student/applications/${a.id}`}
                  title={a.job_title}
                >
                  Open Application →
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
