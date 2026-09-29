import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import AdminDashboard from "./features/admin/AdminDashboard";
import { AdminAudit, AdminJobs, AdminKnowledge, AdminRuns, AdminSkills, AdminUsers } from "./features/admin/AdminPages";
import LoginPage from "./features/auth/LoginPage";
import { ClaimAccountPage, DevOutboxPage, ForgotPasswordPage, ResetPasswordPage } from "./features/auth/AccountPages";
import SignupPage from "./features/auth/SignupPage";
import CareerPage from "./features/career/CareerPage";
import CandidatePage from "./features/company/CandidatePage";
import CompanyJobDetailPage from "./features/company/CompanyJobDetailPage";
import CompanyJobsPage from "./features/company/CompanyJobsPage";
import CompanyQuestionsPage from "./features/company/CompanyQuestionsPage";
import QuestionBankPage from "./features/company/QuestionBankPage";
import InstitutionDashboard from "./features/institution/InstitutionDashboard";
import InstitutionStudentPage from "./features/institution/InstitutionStudentPage";
import JobDetailPage from "./features/jobs/JobDetailPage";
import JobsFeedPage from "./features/jobs/JobsFeedPage";
import ApplicationDetailPage from "./features/student/ApplicationDetailPage";
import ApplicationsPage from "./features/student/ApplicationsPage";
import ProfilePage from "./features/student/ProfilePage";
import SkillDetailPage from "./features/student/SkillDetailPage";
import StudentDashboard from "./features/student/StudentDashboard";
import { useAuthStore, type Role } from "./stores/authStore";

const HOME: Record<string, string> = {
  STUDENT: "/student", PLATFORM_ADMIN: "/admin", INSTITUTION_ADMIN: "/institution", PLACEMENT_OFFICER: "/institution",
  FACULTY: "/institution", DEPARTMENT_HEAD: "/institution", COMPANY_ADMIN: "/company", RECRUITER: "/company", HIRING_MANAGER: "/company",
};

function RequireRole({ roles, children }: { roles: Role[]; children: React.ReactElement }) {
  const { token, role } = useAuthStore();
  if (!token) return <Navigate to="/login" replace />;
  if (!role || !roles.includes(role)) return <Navigate to={HOME[role ?? ""] ?? "/login"} replace />;
  return children;
}

export default function App() {
  const role = useAuthStore((s) => s.role);
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />
      <Route path="/claim" element={<ClaimAccountPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/dev/outbox" element={<DevOutboxPage />} />

      <Route path="/student" element={<RequireRole roles={["STUDENT"]}><AppShell nav={[
        { to: "/student", label: "Dashboard" }, { to: "/student/jobs", label: "Jobs" },
        { to: "/student/applications", label: "Applications" }, { to: "/student/profile", label: "Profile & resume" }]} /></RequireRole>}>
        <Route index element={<StudentDashboard />} />
        <Route path="jobs" element={<JobsFeedPage />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route path="applications" element={<ApplicationsPage />} />
        <Route path="applications/:applicationId" element={<ApplicationDetailPage />} />
        <Route path="profile" element={<ProfilePage />} />
        <Route path="skills/:skillId" element={<SkillDetailPage />} />
        <Route path="career/:jobId" element={<CareerPage />} />
      </Route>

      <Route path="/company" element={<RequireRole roles={["COMPANY_ADMIN", "RECRUITER", "HIRING_MANAGER"]}><AppShell nav={[
        { to: "/company", label: "Jobs" }, { to: "/company/questions", label: "Question bank" }]} /></RequireRole>}>
        <Route index element={<CompanyJobsPage />} />
        <Route path="jobs/:jobId" element={<CompanyJobDetailPage />} />
        <Route path="applications/:applicationId" element={<CandidatePage />} />
        <Route path="questions" element={<CompanyQuestionsPage />} />
      </Route>

      <Route path="/institution" element={<RequireRole roles={["INSTITUTION_ADMIN", "PLACEMENT_OFFICER", "FACULTY", "DEPARTMENT_HEAD"]}>
        <AppShell nav={[{ to: "/institution", label: "Analytics" }]} /></RequireRole>}>
        <Route index element={<InstitutionDashboard />} />
        <Route path="institutions/:institutionId/students/:studentId" element={<InstitutionStudentPage />} />
      </Route>

      <Route path="/admin" element={<RequireRole roles={["PLATFORM_ADMIN"]}><AppShell nav={[
        { to: "/admin", label: "Overview & cost" }, { to: "/admin/skills", label: "Skills" }, { to: "/admin/questions", label: "Questions" },
        { to: "/admin/knowledge", label: "Knowledge" }, { to: "/admin/runs", label: "AI & agent runs" }, { to: "/admin/jobs", label: "Background jobs" },
        { to: "/admin/users", label: "Users" }, { to: "/admin/audit", label: "Audit" }]} /></RequireRole>}>
        <Route index element={<AdminDashboard />} />
        <Route path="skills" element={<AdminSkills />} />
        <Route path="questions" element={<QuestionBankPage admin />} />
        <Route path="knowledge" element={<AdminKnowledge />} />
        <Route path="runs" element={<AdminRuns />} />
        <Route path="jobs" element={<AdminJobs />} />
        <Route path="users" element={<AdminUsers />} />
        <Route path="audit" element={<AdminAudit />} />
      </Route>

      <Route path="*" element={<Navigate to={role ? HOME[role] ?? "/login" : "/login"} replace />} />
    </Routes>
  );
}
