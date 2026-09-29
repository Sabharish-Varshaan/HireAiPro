import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { apiError } from "../../components/ui";

// Shared auth shell used across all unauthenticated pages
export function AuthShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen flex">
      {/* Brand panel — shown on wider screens */}
      <div className="hidden lg:flex lg:w-[420px] xl:w-[480px] flex-col justify-between bg-[#0E1520] p-10 shrink-0">
        <div>
          <p className="text-xl font-bold text-white tracking-tight">
            HireAI<span className="text-blue-400">Pro</span>
          </p>
          <p className="text-xs text-gray-400 mt-1">Intelligent hiring & placement</p>
        </div>
        <div className="space-y-6">
          {[
            { title: "Skill-verified matching", body: "AI scores candidates against job requirements using verified assessment results — not just resume keywords." },
            { title: "Adaptive AI interviews", body: "Context-aware conversations that go deeper on relevant skills and surface hidden strengths." },
            { title: "Placement office tools", body: "Full analytics, student portfolio management, and placement funnel for institutions." },
          ].map((f) => (
            <div key={f.title}>
              <p className="text-sm font-semibold text-white">{f.title}</p>
              <p className="text-xs text-gray-400 mt-1 leading-relaxed">{f.body}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-gray-600">© 2026 HireAiPro</p>
      </div>

      {/* Form panel */}
      <div className="flex-1 flex items-center justify-center bg-gray-50 p-6">
        <div className="w-full max-w-sm">
          {/* Mobile brand mark */}
          <p className="text-lg font-bold text-gray-900 mb-6 lg:hidden">
            HireAI<span className="text-blue-600">Pro</span>
          </p>
          {children}
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition";

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
      navigate(
        role.toLowerCase().includes("student")
          ? "/student"
          : role.toLowerCase().includes("institution") ||
            role.toLowerCase().includes("faculty") ||
            role.toLowerCase().includes("placement") ||
            role.toLowerCase().includes("department")
          ? "/institution"
          : role === "PLATFORM_ADMIN"
          ? "/admin"
          : "/company"
      );
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Login failed. Please check your details and try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Welcome back</h1>
          <p className="text-sm text-gray-500 mt-1">Sign in to your HireAiPro account</p>
        </div>

        <div className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="login-email" className="block text-xs font-medium text-gray-700">Email address</label>
            <input
              id="login-email"
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
            <div className="flex items-center justify-between">
              <label htmlFor="login-password" className="block text-xs font-medium text-gray-700">Password</label>
              <a href="/forgot-password" className="text-xs text-blue-600 hover:underline">Forgot password?</a>
            </div>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              required
              className={inputCls}
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
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
          {loading ? "Signing in…" : "Sign in"}
        </button>

        <p className="text-xs text-gray-500 text-center">
          Don't have an account?{" "}
          <a href="/signup" className="text-blue-600 hover:underline font-medium">Sign up</a>
        </p>
      </form>
    </AuthShell>
  );
}
