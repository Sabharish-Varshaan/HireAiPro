import { apiError } from "../../components/ui";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";

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
        email, password, full_name: fullName, role,
        company_name: role === "RECRUITER" ? orgName : undefined, institution_name: role === "PLACEMENT_OFFICER" ? orgName : undefined });
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
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={submit} className="bg-white shadow-sm border border-gray-200 rounded-lg p-8 w-full max-w-sm space-y-4">
        <h1 className="text-xl font-semibold text-gray-900">Create account</h1>
        <input className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Full name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        <input className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        <select className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>{r.label}</option>
          ))}
        </select>
        {role !== "STUDENT" && (
          <input className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" data-testid="org-name"
            placeholder={role === "RECRUITER" ? "Company name" : "Institution name"} value={orgName} onChange={(e) => setOrgName(e.target.value)} />
        )}
        {role === "STUDENT" && <p className="text-xs text-gray-500">Invited by your institution? Use the link in your invitation email instead.</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button disabled={loading} className="w-full bg-gray-900 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50">
          {loading ? "Creating..." : "Create account"}
        </button>
        <p className="text-xs text-gray-500 text-center">
          Already have an account? <a className="underline" href="/login">Sign in</a>
        </p>
      </form>
    </div>
  );
}
