import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import {
  Badge,
  Button,
  Card,
  Empty,
  MetricCard,
  PageHeader,
  SkeletonCard,
  humanize,
} from "../../components/ui";

const BAND_LABEL: Record<string, string> = {
  strong: "Strong",
  developing: "Developing",
  emerging: "Emerging",
  not_yet_demonstrated: "Not yet demonstrated",
};
const BAND_TONE: Record<string, string> = {
  strong: "green",
  developing: "blue",
  emerging: "amber",
  not_yet_demonstrated: "gray",
};

export default function StudentDashboard() {
  const fullName = useAuthStore((s) => s.fullName);

  const { data: profile, isLoading: profileLoading } = useQuery({
    queryKey: ["student-me"],
    queryFn: () => api.get("/students/me").then((r) => r.data),
  });
  const { data: applications, isLoading: appsLoading } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });
  const { data: skills, isLoading: skillsLoading } = useQuery({
    queryKey: ["student-skills", profile?.id],
    queryFn: () => api.get(`/evidence/students/${profile.id}/skills`).then((r) => r.data),
    enabled: !!profile?.id,
  });

  const isLoading = profileLoading || appsLoading || skillsLoading;

  if (isLoading) {
    return (
      <div className="max-w-5xl space-y-6">
        <SkeletonCard />
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  const resumeStatus = profile?.resume_document_id
    ? humanize(profile.resume_parse_status)
    : "Not uploaded";

  const resumeTone =
    profile?.resume_parse_status === "PARSED"
      ? "success"
      : profile?.resume_parse_status === "FAILED"
      ? "danger"
      : profile?.resume_parse_status === "PROCESSING" || profile?.resume_parse_status === "PENDING"
      ? "warning"
      : "default";

  const activeAppsCount = applications?.length ?? 0;
  const verifiedSkillsCount = skills?.length ?? 0;

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title={`Welcome back, ${fullName?.split(" ")[0] ?? "Student"}`}
        description="Track your hiring pipeline, assessments, and verified skill profile."
        actions={
          <div className="flex gap-2">
            <Link to="/student/jobs">
              <Button size="sm">Browse Roles</Button>
            </Link>
            <Link to="/student/profile">
              <Button variant="secondary" size="sm">
                Edit Profile
              </Button>
            </Link>
          </div>
        }
      />

      {/* Metric Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard
          label="Resume Status"
          value={resumeStatus}
          tone={resumeTone as any}
          sub={
            !profile?.resume_document_id ? (
              <Link to="/student/profile" className="text-xs text-blue-600 hover:underline">
                Upload resume →
              </Link>
            ) : undefined
          }
        />
        <MetricCard
          label="Active Applications"
          value={activeAppsCount}
          tone="info"
          sub={
            activeAppsCount > 0 ? (
              <Link to="/student/applications" className="text-xs text-blue-600 hover:underline">
                View all applications →
              </Link>
            ) : undefined
          }
        />
        <MetricCard
          label="Verified Skills"
          value={verifiedSkillsCount}
          tone="success"
          sub="Demonstrated via assessments"
        />
      </div>

      {/* Quick Action Banner if onboarding / low activity */}
      {(!profile?.resume_document_id || activeAppsCount === 0) && (
        <div className="bg-gradient-to-r from-blue-50 to-indigo-50 border border-blue-200 rounded-xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <h2 className="text-sm font-semibold text-blue-950">Get ready for upcoming placements</h2>
            <p className="text-xs text-blue-800 leading-relaxed max-w-xl">
              Upload your resume to extract your background, explore verified job opportunities, and complete technical assessments to build your verified skill badges.
            </p>
          </div>
          <div className="flex gap-2 shrink-0">
            {!profile?.resume_document_id && (
              <Link to="/student/profile">
                <Button size="sm">Upload Resume</Button>
              </Link>
            )}
            <Link to="/student/jobs">
              <Button variant="secondary" size="sm">
                Browse Roles
              </Button>
            </Link>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Recent Applications Preview */}
        <Card
          title="Recent Applications"
          description="Your ongoing applications and current stages."
          actions={
            activeAppsCount > 0 ? (
              <Link to="/student/applications" className="text-xs text-blue-600 hover:underline font-medium">
                View all ({activeAppsCount})
              </Link>
            ) : null
          }
        >
          {(applications ?? []).length === 0 ? (
            <Empty
              action={
                <Link to="/student/jobs">
                  <Button size="sm">Explore Open Roles</Button>
                </Link>
              }
            >
              You haven't applied to any roles yet.
            </Empty>
          ) : (
            <div className="divide-y divide-gray-100">
              {applications.slice(0, 4).map((a: any) => (
                <div key={a.id} className="py-3 flex items-center justify-between gap-3 text-sm">
                  <div className="min-w-0">
                    <p className="font-medium text-gray-900 truncate">{a.job_title}</p>
                    <p className="text-xs text-gray-500">{a.organization_name}</p>
                  </div>
                  <div className="flex items-center gap-2.5 shrink-0">
                    <Badge>{a.status}</Badge>
                    <Link
                      to={`/student/applications/${a.id}`}
                      className="text-xs font-semibold text-blue-600 hover:text-blue-800"
                    >
                      Open →
                    </Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>

        {/* Verified Skills */}
        <Card
          title="Verified Competencies"
          description="Skill bands demonstrated through technical tests and AI interviews."
        >
          {(skills ?? []).length === 0 ? (
            <Empty>
              No verified evidence yet. Take assessments or technical interviews to build your validated competency badges.
            </Empty>
          ) : (
            <div className="divide-y divide-gray-100">
              {skills.map((s: any) => (
                <div key={s.skill_id} className="py-2.5 flex items-center justify-between text-sm">
                  <Link
                    className="font-medium text-gray-800 hover:text-blue-600 transition"
                    to={`/student/skills/${s.skill_id}`}
                  >
                    {s.skill_name}
                  </Link>
                  <Badge tone={BAND_TONE[s.band] ?? "gray"}>
                    {BAND_LABEL[s.band] ?? s.band}
                  </Badge>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
