import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api } from "../../api/client";
import { apiError } from "../../components/ui";
import { useAuthStore } from "../../stores/authStore";

const box = "w-full border border-gray-300 rounded-md px-3 py-2 text-sm";
const Shell = ({ title, children }: { title: string; children: React.ReactNode }) => (
  <div className="min-h-screen flex items-center justify-center bg-gray-50">
    <div className="bg-white shadow-sm border border-gray-200 rounded-lg p-8 w-full max-w-sm space-y-4">
      <h1 className="text-xl font-semibold text-gray-900">{title}</h1>{children}</div>
  </div>
);
const Btn = ({ disabled, children }: { disabled?: boolean; children: React.ReactNode }) => (
  <button disabled={disabled} className="w-full bg-gray-900 text-white rounded-md py-2 text-sm font-medium disabled:opacity-50">{children}</button>
);

/** Invitation link target: the invited person chooses their own password. */
export function ClaimAccountPage() {
  const token = useSearchParams()[0].get("token") ?? "";
  const info = useQuery({ queryKey: ["invite", token], enabled: !!token, retry: false,
    queryFn: () => api.get(`/auth/invitations/${encodeURIComponent(token)}`).then((r) => r.data) });
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const setAuth = useAuthStore((s) => s.setAuth);
  const navigate = useNavigate();
  const qc = useQueryClient();

  if (!token || info.error) return <Shell title="Invitation not valid"><p className="text-sm text-gray-600" data-testid="invite-invalid">This invitation link is invalid, already used, or has expired. Ask your placement office to resend it.</p></Shell>;
  if (info.isLoading) return <Shell title="Checking invitation…"><p className="text-sm text-gray-500">One moment.</p></Shell>;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (password !== confirm) return setError("Passwords do not match");
    setBusy(true);
    try {
      const r = await api.post("/auth/invitations/accept", { token, password });
      qc.clear();
      setAuth(r.data.access_token, r.data.user_id, r.data.role, r.data.full_name);
      navigate(r.data.role === "STUDENT" ? "/student/profile" : "/");
    } catch (err: any) { setError(err.response ? apiError(err) : "Could not activate account"); } finally { setBusy(false); }
  }
  return (
    <Shell title="Activate your account">
      <form onSubmit={submit} className="space-y-3">
        <p className="text-sm text-gray-600">{info.data.full_name ? `Welcome, ${info.data.full_name}. ` : ""}{info.data.institution_name ? `${info.data.institution_name} invited you. ` : ""}Choose your own password for <b>{info.data.email}</b>.</p>
        <input className={box} type="password" placeholder="New password (min 8 characters)" value={password} onChange={(e) => setPassword(e.target.value)} />
        <input className={box} type="password" placeholder="Confirm password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <Btn disabled={busy}>{busy ? "Activating…" : "Activate account"}</Btn>
      </form>
    </Shell>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    try { await api.post("/auth/password/forgot", { email }); setDone(true); } catch (err: any) { setError(err.response ? apiError(err) : "Request failed"); }
  }
  return (
    <Shell title="Reset password">
      {done ? <p className="text-sm text-gray-600" data-testid="reset-sent">If an account exists for that email, a reset link has been sent.</p> : (
        <form onSubmit={submit} className="space-y-3">
          <input className={box} type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Btn>Send reset link</Btn>
        </form>)}
      <p className="text-xs text-gray-500 text-center"><a className="underline" href="/login">Back to sign in</a></p>
    </Shell>
  );
}

export function ResetPasswordPage() {
  const token = useSearchParams()[0].get("token") ?? "";
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault(); setError(null);
    if (password !== confirm) return setError("Passwords do not match");
    try { await api.post("/auth/password/reset", { token, password }); setDone(true); } catch (err: any) { setError(err.response ? apiError(err) : "Reset failed"); }
  }
  return (
    <Shell title="Choose a new password">
      {done ? <p className="text-sm text-green-700" data-testid="reset-done">Password updated. <a className="underline" href="/login">Sign in</a></p> : (
        <form onSubmit={submit} className="space-y-3">
          <input className={box} type="password" placeholder="New password (min 8 characters)" value={password} onChange={(e) => setPassword(e.target.value)} />
          <input className={box} type="password" placeholder="Confirm password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <Btn>Update password</Btn>
        </form>)}
    </Shell>
  );
}

/** Development/demo only: stands in for email delivery. The API answers 404 in production. */
export function DevOutboxPage() {
  const q = useQuery({ queryKey: ["outbox"], refetchInterval: 4000, retry: false, queryFn: () => api.get("/dev/email-outbox").then((r) => r.data) });
  return (
    <div className="max-w-3xl mx-auto p-6 space-y-3">
      <h1 className="text-lg font-semibold">Development email outbox</h1>
      <p className="text-xs text-gray-500">No mail provider is connected. Development and demo environments only.</p>
      {q.error && <p className="text-sm text-red-600">Outbox is not available in this environment.</p>}
      {(q.data ?? []).map((m: any) => (
        <div key={m.id} className="border border-gray-200 rounded-md p-3 text-sm bg-white">
          <p><b>{m.subject}</b> → {m.to} <span className="text-xs text-gray-400">{new Date(m.created_at).toLocaleString()}</span></p>
          {m.link && <a className="underline text-xs break-all" href={m.link}>{m.link}</a>}
        </div>))}
    </div>
  );
}
