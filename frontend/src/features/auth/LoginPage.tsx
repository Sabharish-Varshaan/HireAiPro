import { apiError } from "../../components/ui";
import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
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
      const res = await api.post("/auth/login", { email, password });
      const { access_token, user_id, role, full_name } = res.data;
      qc.clear();
      setAuth(access_token, user_id, role, full_name);
      navigate(`/${role.toLowerCase().includes("student") ? "student" : role.toLowerCase().includes("institution") || role.toLowerCase().includes("faculty") || role.toLowerCase().includes("placement") || role.toLowerCase().includes("department") ? "institution" : role === "PLATFORM_ADMIN" ? "admin" : "company"}`);
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50">
      <form onSubmit={submit} className="bg-white shadow-sm border border-gray-200 rounded-lg p-8 w-full max-w-sm space-y-4">
        <h1 className="text-xl font-semibold text-gray-900">Sign in</h1>
        <input
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="Email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="Password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          disabled={loading}
          className="w-full bg-gray-900 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading ? "Signing in..." : "Sign in"}
        </button>
        <p className="text-xs text-gray-500 text-center">
          No account? <a className="underline" href="/signup">Sign up</a>
        </p>
      </form>
    </div>
  );
}
