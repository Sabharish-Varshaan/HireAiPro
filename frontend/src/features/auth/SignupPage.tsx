import { apiError } from "../../components/ui";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { AuthShell } from "./LoginPage";

const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition";

const ROLES = [
  { value: "STUDENT", label: "Student" },
  { value: "RECRUITER", label: "Recruiter / Company" },
  { value: "PLACEMENT_OFFICER", label: "Placement Officer (institution)" },
];

export default function SignupPage() {
  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState("STUDENT");
  const [orgName, setOrgName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const navigate = useNavigate();
  const qc = useQueryClient();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.post("/auth/signup", {
        email,
        password,
        full_name: fullName,
        role,
        company_name: role === "RECRUITER" ? orgName : undefined,
        institution_name: role === "PLACEMENT_OFFICER" ? orgName : undefined,
      });
      const { access_token, user_id, role: r, full_name: fn } = res.data;
      qc.clear();
      setAuth(access_token, user_id, r, fn);
      if (r === "STUDENT") navigate("/student");
      else if (r === "PLATFORM_ADMIN") navigate("/admin");
      else if (r === "PLACEMENT_OFFICER") navigate("/institution");
      else navigate("/company");
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Signup failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Create your account</h1>
          <p className="text-sm text-gray-500 mt-1">Get started with HireAiPro today.</p>
        </div>

        <div className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="signup-name" className="block text-xs font-medium text-gray-700">Full name</label>
            <input
              id="signup-name"
              type="text"
              autoComplete="name"
              required
              className={inputCls}
              placeholder="Your full name"
              value={fullName}
              onChange={(e) => setFullName(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="signup-email" className="block text-xs font-medium text-gray-700">Email address</label>
            <input
              id="signup-email"
              type="email"
              autoComplete="email"
              required
              className={inputCls}
              placeholder="you@company.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="signup-password" className="block text-xs font-medium text-gray-700">Password</label>
            <input
              id="signup-password"
              type="password"
              autoComplete="new-password"
              required
              minLength={8}
              className={inputCls}
              placeholder="Minimum 8 characters"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>

          <div className="space-y-1">
            <label htmlFor="signup-role" className="block text-xs font-medium text-gray-700">I am a…</label>
            <select
              id="signup-role"
              className={inputCls}
              value={role}
              onChange={(e) => setRole(e.target.value)}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>{r.label}</option>
              ))}
            </select>
          </div>

          {role !== "STUDENT" && (
            <div className="space-y-1">
              <label htmlFor="signup-org" className="block text-xs font-medium text-gray-700">
                {role === "RECRUITER" ? "Company name" : "Institution name"}
              </label>
              <input
                id="signup-org"
                type="text"
                data-testid="org-name"
                required
                className={inputCls}
                placeholder={role === "RECRUITER" ? "Acme Corp" : "University of Technology"}
                value={orgName}
                onChange={(e) => setOrgName(e.target.value)}
              />
            </div>
          )}

          {role === "STUDENT" && (
            <div className="rounded-md border border-blue-200 bg-blue-50 px-3 py-2.5 text-xs text-blue-700">
              <strong>Invited by your institution?</strong> Use the link in your invitation email instead — it will set up your account correctly.
            </div>
          )}
        </div>

        {error && (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-blue-700 hover:bg-blue-800 text-white rounded-md py-2.5 text-sm font-medium transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
        >
          {loading ? "Creating account…" : "Create account"}
        </button>

        <p className="text-xs text-gray-500 text-center">
          Already have an account?{" "}
          <a href="/login" className="text-blue-600 hover:underline font-medium">Sign in</a>
        </p>
      </form>
    </AuthShell>
  );
}
