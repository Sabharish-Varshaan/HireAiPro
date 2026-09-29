import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Card, ErrorBox, Loading, Table } from "../../components/ui";

const BAND_LABEL: Record<string, string> = { strong: "Strong", developing: "Developing", emerging: "Emerging", not_yet_demonstrated: "Not yet demonstrated" };
const BAND_TONE: Record<string, string> = { strong: "green", developing: "blue", emerging: "amber", not_yet_demonstrated: "gray" };

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
      <Card title="Your level">
        <p className="text-sm"><Badge tone={BAND_TONE[x.band] ?? "gray"}>{BAND_LABEL[x.band] ?? x.band}</Badge></p>
        <p className="text-xs text-gray-500">Based only on verified evidence (assessments, coding, interviews). Resume claims help decide what to assess but do not count.</p>
      </Card>
      <Card title="What this is based on">
        <Table head={["Source", "Counts toward level", "When"]}>
          {x.evidence.map((e: any) => (
            <tr key={e.id}><td className="py-1 pr-3"><Badge tone={e.counts_toward_skill ? "blue" : "gray"}>{e.source_type}</Badge></td>
              <td className="pr-3">{e.counts_toward_skill ? "yes" : "no (claim)"}</td><td className="text-xs text-gray-500">{new Date(e.created_at).toLocaleString()}</td></tr>
          ))}
        </Table>
      </Card>
    </div>
  );
}
