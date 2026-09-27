import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

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
  const skillIds = (skills ?? []).map((s: any) => s.skill_id).join(",");
  const { data: skillDetails } = useQuery({
    queryKey: ["skill-details", skillIds],
    queryFn: () => api.get("/skills/by-ids", { params: { ids: skillIds } }).then((r) => r.data),
    enabled: skillIds.length > 0,
  });
  const skillNameById: Record<string, string> = Object.fromEntries(
    (skillDetails ?? []).map((s: any) => [s.id, s.canonical_name])
  );

  return (
    <div className="space-y-6 max-w-4xl">
      <h1 className="text-lg font-semibold text-gray-900">Your profile</h1>
      <div className="bg-white border border-gray-200 rounded-lg p-4 grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-gray-500">Resume status</p>
          <p className="font-medium">{profile?.resume_parse_status ?? "—"}</p>
        </div>
        <div>
          <p className="text-gray-500">Applications</p>
          <p className="font-medium">{applications?.length ?? 0}</p>
        </div>
        <div>
          <p className="text-gray-500">Verified skills</p>
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
            <span className="text-gray-700">{skillNameById[s.skill_id] ?? s.skill_id}</span>
            <div className="flex items-center gap-2">
              <div className="w-32 h-2 bg-gray-100 rounded-full overflow-hidden">
                <div className="h-full bg-gray-900" style={{ width: `${s.estimated_level * 100}%` }} />
              </div>
              <span className="text-xs text-gray-500 w-10 text-right">{Math.round(s.estimated_level * 100)}%</span>
            </div>
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
