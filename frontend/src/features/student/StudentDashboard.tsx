import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Badge } from "../../components/ui";

const BAND_LABEL: Record<string, string> = { strong: "Strong", developing: "Developing", emerging: "Emerging", not_yet_demonstrated: "Not yet demonstrated" };
const BAND_TONE: Record<string, string> = { strong: "green", developing: "blue", emerging: "amber", not_yet_demonstrated: "gray" };

export default function StudentDashboard() {
  const { data: profile } = useQuery({
    queryKey: ["student-me"],
    queryFn: () => api.get("/students/me").then((r) => r.data),
  });
  const { data: applications } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });
  const { data: skills } = useQuery({
    queryKey: ["student-skills", profile?.id],
    queryFn: () => api.get(`/evidence/students/${profile.id}/skills`).then((r) => r.data),
    enabled: !!profile?.id,
  });
  return (
    <div className="space-y-6 max-w-4xl">
      <h1 className="text-lg font-semibold text-gray-900">Your profile</h1>
      <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-gray-500">Resume status</p>
          <p className="font-medium">{profile?.resume_document_id ? profile.resume_parse_status : "Not uploaded"}</p>
        </div>
        <div>
          <p className="text-gray-500">Applications</p>
          <p className="font-medium">{applications?.length ?? 0}</p>
        </div>
        <div>
          <p className="text-gray-500">Verified skills (assessed)</p>
          <p className="font-medium">{skills?.length ?? 0}</p>
        </div>
      </div>

      <h2 className="text-sm font-semibold text-gray-700">Verified skill levels</h2>
      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        {(skills ?? []).length === 0 && (
          <p className="p-4 text-sm text-gray-500">
            No verified evidence yet. Take assessments or interviews to build your skill profile.
          </p>
        )}
        {(skills ?? []).map((s: any) => (
          <div key={s.skill_id} className="p-3 flex items-center justify-between text-sm">
            <Link className="text-gray-700 underline" to={`/student/skills/${s.skill_id}`}>{s.skill_name}</Link>
            <Badge tone={BAND_TONE[s.band] ?? "gray"}>{BAND_LABEL[s.band] ?? s.band}</Badge>
          </div>
        ))}
      </div>

      <div className="flex gap-3 text-sm">
        <Link to="/student/jobs" className="text-gray-900 underline">Browse jobs</Link>
        <Link to="/student/applications" className="text-gray-900 underline">My applications</Link>
      </div>
    </div>
  );
}
