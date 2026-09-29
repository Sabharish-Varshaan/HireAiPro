import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { useAuthStore } from "../../stores/authStore";
import { apiError } from "../../components/ui";
import { AuthShell } from "./LoginPage";

const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm text-gray-900 placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition";

const PrimaryBtn = ({ disabled, children }: { disabled?: boolean; children: React.ReactNode }) => (
  <button
    type="submit"
    disabled={disabled}
    className="w-full bg-blue-700 hover:bg-blue-800 text-white rounded-md py-2.5 text-sm font-medium transition-colors disabled:opacity-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-blue-400"
  >
    {children}
  </button>
);

/** Invitation link target: the invited person chooses their own password. */
export function ClaimAccountPage() {
  const token = useSearchParams()[0].get("token") ?? "";
  const info = useQuery({
    queryKey: ["invite", token],
    enabled: !!token,
    retry: false,
    queryFn: () => api.get(`/auth/invitations/${encodeURIComponent(token)}`).then((r) => r.data),
  });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const navigate = useNavigate();
  const qc = useQueryClient();

  if (!token || info.error)
    return (
      <AuthShell>
        <div className="space-y-4">
          <div>
            <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Invitation not valid</h1>
            <p className="text-sm text-gray-500 mt-1" data-testid="invite-invalid">
              This invitation link is invalid, already used, or has expired. Ask your placement office to resend it.
            </p>
          </div>
          <a href="/login" className="text-sm text-blue-600 hover:underline">Back to sign in →</a>
        </div>
      </AuthShell>
    );

  if (info.isLoading)
    return (
      <AuthShell>
        <div className="space-y-2">
          <h1 className="text-2xl font-semibold text-gray-900">Checking invitation…</h1>
          <p className="text-sm text-gray-500">One moment, please.</p>
        </div>
      </AuthShell>
    );

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      const r = await api.post("/auth/invitations/accept", { token, password });
      qc.clear();
      setAuth(r.data.access_token, r.data.user_id, r.data.role, r.data.full_name);
      navigate(r.data.role === "STUDENT" ? "/student/profile" : "/");
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Could not activate account");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AuthShell>
      <form onSubmit={submit} className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Activate your account</h1>
          <p className="text-sm text-gray-600 mt-1">
            {info.data.full_name ? `Welcome, ${info.data.full_name}. ` : ""}
            {info.data.institution_name ? `${info.data.institution_name} has invited you. ` : ""}
            Choose a password for <strong>{info.data.email}</strong>.
          </p>
        </div>

        <div className="space-y-3">
          <div className="space-y-1">
            <label htmlFor="claim-password" className="block text-xs font-medium text-gray-700">New password</label>
            <input
              id="claim-password"
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
            <label htmlFor="claim-confirm" className="block text-xs font-medium text-gray-700">Confirm password</label>
            <input
              id="claim-confirm"
              type="password"
              autoComplete="new-password"
              required
              className={inputCls}
              placeholder="Re-enter password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
            />
          </div>
        </div>

        {error && (
          <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
            {error}
          </div>
        )}

        <PrimaryBtn disabled={busy}>{busy ? "Activating…" : "Activate account"}</PrimaryBtn>
      </form>
    </AuthShell>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/auth/password/forgot", { email });
      setDone(true);
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Request failed");
    }
  }

  return (
    <AuthShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Reset your password</h1>
          <p className="text-sm text-gray-500 mt-1">
            Enter your email and we'll send you a reset link.
          </p>
        </div>

        {done ? (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700" data-testid="reset-sent">
            If an account exists for that email, a reset link has been sent. Check your inbox.
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-1">
              <label htmlFor="forgot-email" className="block text-xs font-medium text-gray-700">Email address</label>
              <input
                id="forgot-email"
                type="email"
                autoComplete="email"
                required
                className={inputCls}
                placeholder="you@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </div>
            {error && (
              <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
            <PrimaryBtn>Send reset link</PrimaryBtn>
          </form>
        )}

        <p className="text-xs text-center">
          <a href="/login" className="text-blue-600 hover:underline">← Back to sign in</a>
        </p>
      </div>
    </AuthShell>
  );
}

export function ResetPasswordPage() {
  const token = useSearchParams()[0].get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("Passwords do not match.");
    try {
      await api.post("/auth/password/reset", { token, password });
      setDone(true);
    } catch (err: any) {
      setError(err.response ? apiError(err) : "Reset failed");
    }
  }

  return (
    <AuthShell>
      <div className="space-y-5">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 tracking-tight">Choose a new password</h1>
        </div>

        {done ? (
          <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-3 text-sm text-emerald-700" data-testid="reset-done">
            Password updated.{" "}
            <a href="/login" className="underline font-medium">Sign in →</a>
          </div>
        ) : (
          <form onSubmit={submit} className="space-y-4">
            <div className="space-y-3">
              <div className="space-y-1">
                <label htmlFor="reset-password" className="block text-xs font-medium text-gray-700">New password</label>
                <input
                  id="reset-password"
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
                <label htmlFor="reset-confirm" className="block text-xs font-medium text-gray-700">Confirm password</label>
                <input
                  id="reset-confirm"
                  type="password"
                  autoComplete="new-password"
                  required
                  className={inputCls}
                  placeholder="Re-enter password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                />
              </div>
            </div>
            {error && (
              <div role="alert" className="rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700">
                {error}
              </div>
            )}
            <PrimaryBtn>Update password</PrimaryBtn>
          </form>
        )}
      </div>
    </AuthShell>
  );
}

/** Development/demo only: stands in for email delivery. The API answers 404 in production. */
export function DevOutboxPage() {
  const q = useQuery({
    queryKey: ["outbox"],
    refetchInterval: 4000,
    retry: false,
    queryFn: () => api.get("/dev/email-outbox").then((r) => r.data),
  });
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-gray-900">Development email outbox</h1>
        <p className="text-xs text-gray-500 mt-1">No mail provider is connected. Development and demo environments only.</p>
      </div>
      {q.error && (
        <p className="text-sm text-red-600">Outbox is not available in this environment.</p>
      )}
      <div className="space-y-2">
        {(q.data ?? []).map((m: any) => (
          <div key={m.id} className="border border-gray-200 rounded-lg p-4 text-sm bg-white shadow-sm">
            <div className="flex items-center justify-between gap-3">
              <p className="font-medium text-gray-900">{m.subject}</p>
              <span className="text-xs text-gray-400 shrink-0">{new Date(m.created_at).toLocaleString()}</span>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">To: {m.to}</p>
            {m.link && (
              <a className="text-xs text-blue-600 hover:underline break-all mt-2 block" href={m.link}>
                {m.link}
              </a>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
