import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Table,
  pct,
} from "../../components/ui";

export default function JobDetailPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();

  const job = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data),
  });
  const apps = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });

  const existing = apps.data?.find((a: any) => a.job_id === jobId);
  const apply = useMutation({
    mutationFn: () => api.post("/applications", { job_id: jobId }).then((r) => r.data),
    onSuccess: (a) => navigate(`/student/applications/${a.id}`),
  });

  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} onRetry={job.refetch} />;
  const j = job.data;

  const confirmedSkills = (j.skills ?? []).filter((s: any) => s.confirmed);

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        back={{ label: "All roles", href: "/student/jobs" }}
        title={j.title}
        description={j.organization_name}
        actions={
          existing ? (
            <Link to={`/student/applications/${existing.id}`}>
              <Button size="sm">View Your Application →</Button>
            </Link>
          ) : j.display?.applications_open === false ? (
            <Badge tone="red">Applications Closed</Badge>
          ) : (
            <Button
              onClick={() => apply.mutate()}
              disabled={apply.isPending}
              size="sm"
            >
              {apply.isPending ? "Applying…" : "Apply Now"}
            </Button>
          )
        }
      />

      {/* Role Summary Card */}
      <Card title="Role Overview & Compensation">
        <JobFacts job={j} />
        {j.display?.conversion && j.conversion_notes && (
          <div className="mt-3 p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900">
            <strong>Conversion Opportunity:</strong> {j.conversion_notes}
          </div>
        )}
      </Card>

      {/* Required Competencies */}
      <Card
        title="Required & Preferred Competencies"
        description="These skills will be evaluated through our technical assessment and conversational interview."
      >
        {confirmedSkills.length === 0 ? (
          <Empty>No specific skill requirements listed for this role.</Empty>
        ) : (
          <Table head={["Skill / Competency", "Type", "Expected Level"]}>
            {confirmedSkills.map((s: any) => (
              <tr key={s.id} className="hover:bg-gray-50/50">
                <td className="py-2.5 pr-3 font-medium text-gray-900">
                  {s.canonical_name ?? s.raw_skill_name}
                </td>
                <td className="pr-3">
                  <Badge tone={s.requirement_type === "required" ? "blue" : "gray"}>
                    {s.requirement_type === "required" ? "Required" : "Preferred"}
                  </Badge>
                </td>
                <td className="pr-3 text-xs font-semibold text-gray-800">{pct(s.minimum_level)}</td>
              </tr>
            ))}
          </Table>
        )}
      </Card>

      {/* Full Description */}
      <Card title="Job Description">
        <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
          {j.description_raw || "No detailed description provided."}
        </p>
      </Card>

      {/* Bottom CTA Card */}
      <div className="bg-white border border-gray-200 rounded-xl p-5 flex items-center justify-between shadow-sm">
        <div>
          <h2 className="text-sm font-semibold text-gray-900">Ready to take the next step?</h2>
          <p className="text-xs text-gray-500">
            Submit your profile to begin the proctored assessment and interview process.
          </p>
        </div>
        <div>
          {existing ? (
            <Link
              className="inline-flex items-center text-sm font-semibold text-blue-700 hover:text-blue-900 underline"
              to={`/student/applications/${existing.id}`}
            >
              You applied — open your application →
            </Link>
          ) : j.display?.applications_open === false ? (
            <p className="text-sm font-medium text-red-600" data-testid="applications-closed">
              Applications for this role have closed.
            </p>
          ) : (
            <Button onClick={() => apply.mutate()} disabled={apply.isPending}>
              {apply.isPending ? "Applying…" : "Apply for Role"}
            </Button>
          )}
        </div>
      </div>
      <ErrorBox error={apply.error} />
    </div>
  );
}
