import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Card, ErrorBox, Loading, Table, pct } from "../../components/ui";

export default function SkillDetailPage() {
  const { skillId } = useParams();
  const me = useQuery({ queryKey: ["student-me"], queryFn: () => api.get("/students/me").then((r) => r.data) });
  const d = useQuery({ queryKey: ["skill-detail", me.data?.id, skillId], enabled: !!me.data?.id,
    queryFn: () => api.get(`/evidence/students/${me.data.id}/skills/${skillId}`).then((r) => r.data) });
  if (d.isLoading || me.isLoading) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} onRetry={d.refetch} />;
  const x = d.data;
  return (
    <div className="max-w-4xl space-y-5">
      <Link to="/student" className="text-xs text-gray-500 underline">← Dashboard</Link>
      <h1 className="text-lg font-semibold">{x.skill.canonical_name} <span className="text-sm text-gray-500">{x.skill.category}</span></h1>
      <Card title="Estimate (skill_scoring_v1)">
        {x.estimate ? (
          <p className="text-sm">Level <b>{pct(x.estimate.estimated_level)}</b> · confidence <b>{pct(x.estimate.confidence)}</b> · {x.estimate.evidence_count} scored evidence · {x.estimate.scoring_version}</p>
        ) : <p className="text-sm text-gray-500">No verified level yet — only scored evidence (assessments, coding, interviews, projects) counts.</p>}
        <p className="text-xs text-gray-500">Source weights: {Object.entries(x.weights).map(([k, v]) => `${k} ${pct(v as number)}`).join(" · ")}</p>
      </Card>
      <Card title="Evidence">
        <Table head={["Source", "Score", "Confidence", "Difficulty", "Counts toward level", "When"]}>
          {x.evidence.map((e: any) => (
            <tr key={e.id}><td className="py-1 pr-3"><Badge tone={e.counts_toward_score ? "blue" : "gray"}>{e.source_type}</Badge></td>
              <td className="pr-3">{pct(e.normalized_score)}</td><td className="pr-3">{pct(e.confidence)}</td><td className="pr-3">{e.difficulty ?? "—"}</td>
              <td className="pr-3">{e.counts_toward_score ? "yes" : "no (claim)"}</td><td className="text-xs text-gray-500">{new Date(e.created_at).toLocaleString()}</td></tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
