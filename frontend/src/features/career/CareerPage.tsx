import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table } from "../../components/ui";

export default function CareerPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const [pathId, setPathId] = useState<string | null>(null);
  const gaps = useQuery({ queryKey: ["gaps", jobId], queryFn: () => api.get(`/career/gaps/${jobId}`).then((r) => r.data) });
  const historyQ = useQuery({ queryKey: ["roadmaps"], queryFn: () => api.get("/career/roadmap/history").then((r) => r.data) });
  const latest = pathId ?? historyQ.data?.find((p: any) => p.target_job_id === jobId)?.id;
  const roadmap = useQuery({ queryKey: ["roadmap", latest], enabled: !!latest, queryFn: () => api.get(`/career/roadmap/${latest}`).then((r) => r.data) });
  const build = useMutation({
    mutationFn: () => api.post(`/career/roadmap/${jobId}`).then((r) => r.data),
    onSuccess: (r) => { setPathId(r.learning_path_id); qc.invalidateQueries({ queryKey: ["roadmaps"] }); },
  });

  return (
    <div className="max-w-4xl space-y-5">
      <Link to="/student/applications" className="text-xs text-gray-500 underline">← Applications</Link>
      <Card title="Skills to develop for this role (most important first)">
        {gaps.isLoading && <Loading />}
        <ErrorBox error={gaps.error} onRetry={gaps.refetch} />
        {gaps.data?.length === 0 && <Empty>No gaps — your verified skills meet every requirement.</Empty>}
        {gaps.data?.length > 0 && (
          <Table head={["Priority", "Skill", "Status"]}>
            {gaps.data.map((g: any) => (
              <tr key={g.skill_id}><td className="py-1 pr-3">{g.priority}</td><td className="pr-3">{g.skill_name}</td>
                <td>{g.status === "not_yet_demonstrated" ? "Not yet demonstrated" : "Below the role's requirement"}</td></tr>
            ))}
          </Table>
        )}
      </Card>
      <Card title="Learning roadmap" actions={<Button onClick={() => build.mutate()} disabled={build.isPending}>{build.isPending ? "Building…" : roadmap.data ? "Rebuild" : "Build roadmap"}</Button>}>
        <ErrorBox error={build.error || roadmap.error} />
        {!roadmap.data && !build.isPending && <Empty>No roadmap yet.</Empty>}
        {roadmap.data && (
          <div className="space-y-3">
            <p className="text-sm text-gray-700">{roadmap.data.summary}</p>
            <ol className="space-y-2">
              {roadmap.data.steps.map((s: any, i: number) => (
                <li key={s.skill_id} className="border border-gray-100 rounded p-2">
                  <p className="text-sm font-medium">{i + 1}. {s.skill_name} {s.is_prerequisite && <Badge tone="gray">prerequisite</Badge>}</p>
                  <p className="text-xs text-gray-600">{s.rationale}</p>
                  <ul className="text-xs mt-1 space-y-0.5">
                    {s.resources.map((r: any) => (
                      <li key={r.resource_id}><a className="underline text-blue-700" href={r.url} target="_blank" rel="noreferrer">{r.title}</a> <span className="text-gray-400">· {r.provider} · {r.resource_type}</span></li>
                    ))}
                    {s.resources.length === 0 && <li className="text-gray-400">No curated resource stored for this skill yet.</li>}
                  </ul>
                </li>
              ))}
            </ol>
          </div>
        )}
      </Card>
    </div>
  );
}
