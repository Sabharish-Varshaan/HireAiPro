import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Card, Empty, ErrorBox, Loading, PageHeader, humanize } from "../../components/ui";
import { useRefreshApplication } from "../../hooks/useRefreshApplication";
import { JourneyStrip, StageCards } from "./HiringJourney";

export default function ApplicationDetailPage() {
  const { applicationId } = useParams();
  const refresh = useRefreshApplication();
  const [showLog, setShowLog] = useState(false);

  const app = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}`).then((r) => r.data),
  });
  const pipeline = useQuery({
    queryKey: ["pipeline", applicationId],
    queryFn: () => api.get(`/hiring-pipeline/applications/${applicationId}`).then((r) => r.data),
  });
  const history = useQuery({
    queryKey: ["history", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}/history`).then((r) => r.data),
  });
  const match = useQuery({
    queryKey: ["match", applicationId],
    retry: false,
    queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data),
  });

  if (app.isLoading || pipeline.isLoading) return <Loading />;
  if (app.error) return <ErrorBox error={app.error} onRetry={app.refetch} />;
  if (pipeline.error) return <ErrorBox error={pipeline.error} onRetry={pipeline.refetch} />;
  const a = app.data;
  const stages = pipeline.data?.stages ?? [];
  const decided = ["SHORTLISTED", "OFFER", "REJECTED"].includes(a.status);

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        back={{ label: "My applications", href: "/student/applications" }}
        title={a.job_title}
        description={a.organization_name}
        actions={<Badge>{a.status}</Badge>}
      />

      <Card title="Your hiring journey" description="The steps this employer uses for this role, in order.">
        <JourneyStrip stages={stages} applied={a.applied_at ? new Date(a.applied_at).toLocaleDateString() : undefined} decided={decided} />
      </Card>

      <StageCards applicationId={applicationId!} stages={stages} onChange={refresh} />

      <Card
        title="Final review"
        description="After the last step the hiring team reviews your results. Your verified strengths appear here once that step is complete."
      >
        {!match.data ? (
          <Empty>Your strengths and learning roadmap will appear here once your last step is complete.</Empty>
        ) : (
          <div className="space-y-4 text-sm">
            {[
              ["Demonstrated Strengths", match.data.strengths, "green"],
              ["Competencies to Develop", match.data.skills_to_develop, "amber"],
              ["Not Yet Demonstrated", match.data.missing_skills, "red"],
            ].map(([title, items, tone]: any) => (
              <div key={title} className="space-y-1.5">
                <p className="text-xs font-semibold text-gray-700">{title}</p>
                <div className="flex flex-wrap gap-1.5">
                  {(items ?? []).map((name: string) => (
                    <Badge key={name} tone={tone}>
                      {name}
                    </Badge>
                  ))}
                  {(items ?? []).length === 0 && <span className="text-xs text-gray-400">None identified</span>}
                </div>
              </div>
            ))}
            <div className="pt-2">
              <Link
                className="inline-flex items-center text-xs font-semibold px-3 py-2 rounded-lg bg-blue-50 text-blue-700 hover:bg-blue-100 transition"
                to={`/student/career/${a.job_id}`}
              >
                Build My Learning Roadmap →
              </Link>
            </div>
          </div>
        )}
      </Card>

      <Card
        title="Activity log"
        description="Every change to this application."
        actions={
          <button type="button" className="text-xs font-medium text-blue-700 hover:underline" onClick={() => setShowLog((v) => !v)} aria-expanded={showLog}>
            {showLog ? "Hide" : "Show"}
          </button>
        }
      >
        {!showLog ? null : (history.data ?? []).length === 0 ? (
          <Empty>No history available yet.</Empty>
        ) : (
          <div className="relative pl-6 space-y-4 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-gray-200">
            {(history.data ?? []).map((h: any, i: number) => (
              <div key={i} className="relative flex items-start gap-3 text-xs">
                <div className="absolute -left-6 mt-1 w-3 h-3 rounded-full bg-blue-600 ring-4 ring-white" />
                <div className="flex-1 space-y-0.5">
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-gray-900">{humanize(h.to)}</span>
                    <span className="text-gray-400 font-mono text-[11px]">
                      {new Date(h.at).toLocaleDateString()} {new Date(h.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  {h.note && <p className="text-gray-600 text-xs italic">“{h.note}”</p>}
                </div>
              </div>
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}
