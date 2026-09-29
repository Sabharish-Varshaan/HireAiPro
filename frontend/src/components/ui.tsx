import type { ReactNode } from "react";

export function apiError(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown }; status?: number }; message?: string };
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join("; ");
  if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  if (e?.response?.status) return `Request failed (${e.response.status})`;
  return e?.message ?? "Something went wrong";
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <p className="text-sm text-gray-500 py-2">{label}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-gray-500 py-3">{children}</p>;
}

export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="border border-red-200 bg-red-50 text-red-700 text-sm rounded-md px-3 py-2 flex items-center justify-between gap-3">
      <span>{apiError(error)}</span>
      {onRetry && (
        <button onClick={onRetry} className="text-xs underline shrink-0">
          Retry
        </button>
      )}
    </div>
  );
}

const TONES: Record<string, string> = {
  green: "bg-green-50 text-green-700 border-green-200",
  amber: "bg-amber-50 text-amber-700 border-amber-200",
  red: "bg-red-50 text-red-700 border-red-200",
  blue: "bg-blue-50 text-blue-700 border-blue-200",
  gray: "bg-gray-50 text-gray-600 border-gray-200",
};

const STATUS_TONE: Record<string, string> = {
  READY: "green", COMPLETED: "green", PUBLISHED: "green", APPROVED: "green", ACTIVE: "green", VALIDATED: "blue",
  SHORTLISTED: "green", OFFER: "green", SCORED: "green", REQUIREMENTS_CONFIRMED: "blue", ASSESSMENT_READY: "blue",
  PROCESSING: "amber", RUNNING: "amber", PENDING: "amber", IN_PROGRESS: "amber", DRAFT: "gray", SKILLS_EXTRACTED: "amber",
  APPLIED: "blue", ASSESSMENT_PENDING: "amber", ASSESSMENT_COMPLETED: "blue", INTERVIEW_PENDING: "amber",
  INTERVIEW_COMPLETED: "blue", UNDER_REVIEW: "amber", FAILED: "red", REJECTED: "red", RETIRED: "gray",
  local_fallback: "amber", judge0: "green",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const t = tone ?? STATUS_TONE[String(children)] ?? "gray";
  return <span className={`inline-block text-xs px-2 py-0.5 rounded-full border ${TONES[t]}`}>{String(children).replaceAll("_", " ")}</span>;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      {(title || actions) && (
        <div className="flex items-center justify-between gap-2">
          {title && <h2 className="text-sm font-semibold text-gray-800">{title}</h2>}
          {actions}
        </div>
      )}
      {children}
    </section>
  );
}

export function Button({ children, onClick, disabled, variant = "primary", type = "button" }: {
  children: ReactNode; onClick?: () => void; disabled?: boolean; variant?: "primary" | "secondary" | "danger"; type?: "button" | "submit";
}) {
  const cls = {
    primary: "bg-gray-900 text-white hover:bg-gray-800",
    secondary: "bg-white text-gray-800 border border-gray-300 hover:bg-gray-50",
    danger: "bg-white text-red-700 border border-red-300 hover:bg-red-50",
  }[variant];
  return (
    <button type={type} onClick={onClick} disabled={disabled} className={`text-sm px-3 py-1.5 rounded-md disabled:opacity-50 ${cls}`}>
      {children}
    </button>
  );
}

export const inputCls = "border border-gray-300 rounded-md px-2 py-1.5 text-sm w-full";

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

export function Table({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 border-b border-gray-200">
            {head.map((h) => <th key={h} className="py-2 pr-3 font-medium">{h}</th>)}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">{children}</tbody>
      </table>
    </div>
  );
}
