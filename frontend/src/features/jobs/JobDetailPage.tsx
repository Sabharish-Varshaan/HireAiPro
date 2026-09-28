import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, ErrorBox, Loading, Table, pct } from "../../components/ui";

export default function JobDetailPage() {
  const { jobId } = useParams();
  const navigate = useNavigate();
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data) });
  const apps = useQuery({ queryKey: ["applications-mine"], queryFn: () => api.get("/applications/mine").then((r) => r.data) });
  const existing = apps.data?.find((a: any) => a.job_id === jobId);
  const apply = useMutation({ mutationFn: () => api.post("/applications", { job_id: jobId }).then((r) => r.data), onSuccess: (a) => navigate(`/student/applications/${a.id}`) });

  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} onRetry={job.refetch} />;
  const j = job.data;
  return (
    <div className="max-w-3xl space-y-4">
      <Link to="/student/jobs" className="text-xs text-gray-500 underline">← Jobs</Link>
      <h1 className="text-lg font-semibold">{j.title}</h1>
      <p className="text-xs text-gray-500">{j.organization_name} · {j.location ?? "Location not specified"}</p>
      <Card title="Requirements">
        <Table head={["Skill", "Type", "Expected level"]}>
          {j.skills.filter((s: any) => s.confirmed).map((s: any) => (
            <tr key={s.id}><td className="py-1 pr-3">{s.canonical_name ?? s.raw_skill_name}</td>
              <td className="pr-3"><Badge tone={s.requirement_type === "required" ? "blue" : "gray"}>{s.requirement_type}</Badge></td><td>{pct(s.minimum_level)}</td></tr>
          ))}
        </Table>
      </Card>
      <Card title="Description"><p className="text-sm text-gray-700 whitespace-pre-wrap">{j.description_raw}</p></Card>
      {existing ? <Link className="underline text-sm" to={`/student/applications/${existing.id}`}>You applied — open your application</Link> :
        <Button onClick={() => apply.mutate()} disabled={apply.isPending}>{apply.isPending ? "Applying…" : "Apply"}</Button>}
      <ErrorBox error={apply.error} />
    </div>
  );
}
