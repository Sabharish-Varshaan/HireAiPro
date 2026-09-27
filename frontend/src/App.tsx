import { Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "./components/AppShell";
import AdminDashboard from "./features/admin/AdminDashboard";
import LoginPage from "./features/auth/LoginPage";
import SignupPage from "./features/auth/SignupPage";
import CompanyJobDetailPage from "./features/company/CompanyJobDetailPage";
import CompanyJobsPage from "./features/company/CompanyJobsPage";
import InstitutionDashboard from "./features/institution/InstitutionDashboard";
import JobDetailPage from "./features/jobs/JobDetailPage";
import JobsFeedPage from "./features/jobs/JobsFeedPage";
import ApplicationDetailPage from "./features/student/ApplicationDetailPage";
import ApplicationsPage from "./features/student/ApplicationsPage";
import ProfilePage from "./features/student/ProfilePage";
import StudentDashboard from "./features/student/StudentDashboard";
import { useAuthStore } from "./stores/authStore";

function RequireAuth({ children }: { children: React.ReactElement }) {
  const token = useAuthStore((s) => s.token);
  if (!token) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/signup" element={<SignupPage />} />

      <Route
        path="/student"
        element={
          <RequireAuth>
            <AppShell
              nav={[
                { to: "/student", label: "Dashboard" },
                { to: "/student/jobs", label: "Jobs" },
                { to: "/student/applications", label: "Applications" },
                { to: "/student/profile", label: "Resume" },
              ]}
            />
          </RequireAuth>
        }
      >
        <Route index element={<StudentDashboard />} />
        <Route path="jobs" element={<JobsFeedPage />} />
        <Route path="jobs/:jobId" element={<JobDetailPage />} />
        <Route path="applications" element={<ApplicationsPage />} />
        <Route path="applications/:applicationId" element={<ApplicationDetailPage />} />
        <Route path="profile" element={<ProfilePage />} />
      </Route>

      <Route
        path="/company"
        element={
          <RequireAuth>
            <AppShell nav={[{ to: "/company", label: "Jobs" }]} />
          </RequireAuth>
        }
      >
        <Route index element={<CompanyJobsPage />} />
        <Route path="jobs/:jobId" element={<CompanyJobDetailPage />} />
      </Route>

      <Route
        path="/institution"
        element={
          <RequireAuth>
            <AppShell nav={[{ to: "/institution", label: "Analytics" }]} />
          </RequireAuth>
        }
      >
        <Route index element={<InstitutionDashboard />} />
      </Route>

      <Route
        path="/admin"
        element={
          <RequireAuth>
            <AppShell nav={[{ to: "/admin", label: "Overview" }]} />
          </RequireAuth>
        }
      >
        <Route index element={<AdminDashboard />} />
      </Route>

      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
