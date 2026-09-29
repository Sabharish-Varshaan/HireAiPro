import { useEffect, type ReactNode } from "react";

// ─── Error helper ─────────────────────────────────────────────────────────────
export function apiError(err: unknown): string {
  const e = err as { response?: { data?: { detail?: unknown }; status?: number }; message?: string };
  const d = e?.response?.data?.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x: { msg?: string }) => x.msg ?? JSON.stringify(x)).join("; ");
  if (d && typeof d === "object" && "message" in d) return String((d as { message: unknown }).message);
  if (e?.response?.status) return `Request failed (${e.response.status})`;
  return e?.message ?? "Something went wrong";
}

// ─── Enum humanisation ────────────────────────────────────────────────────────
const LABEL_MAP: Record<string, string> = {
  // Job status
  DRAFT: "Draft",
  SKILLS_EXTRACTED: "Requirements extracted",
  REQUIREMENTS_CONFIRMED: "Requirements confirmed",
  ASSESSMENT_READY: "Ready for assessment",
  PUBLISHED: "Published",
  CLOSED: "Closed",
  // Application status
  APPLIED: "Applied",
  ASSESSMENT_PENDING: "Assessment pending",
  ASSESSMENT_COMPLETED: "Assessment done",
  INTERVIEW_PENDING: "Interview pending",
  INTERVIEW_COMPLETED: "Interview done",
  UNDER_REVIEW: "Under review",
  SHORTLISTED: "Shortlisted",
  OFFER: "Offer made",
  REJECTED: "Not selected",
  // Student record status
  PENDING: "Pending",
  ACTIVE: "Active",
  DISABLED: "Disabled",
  // Resume / general
  PARSED: "Processed",
  PROCESSING: "Processing",
  FAILED: "Failed",
  // Assessment / interview
  SCORED: "Scored",
  SUBMITTED: "Submitted",
  IN_PROGRESS: "In progress",
  READY: "Ready",
  COMPLETED: "Completed",
  PREPARING: "Preparing",
  // Distribution
  OPEN_MARKET: "Open market",
  INSTITUTION: "Institution targeted",
  NOT_REQUIRED: "Not submitted",
  APPROVED: "Approved",
  // Role
  COMPANY_ADMIN: "Company Admin",
  RECRUITER: "Recruiter",
  HIRING_MANAGER: "Hiring Manager",
  PLACEMENT_OFFICER: "Placement Officer",
  STUDENT: "Student",
  PLATFORM_ADMIN: "Platform Admin",
  INSTITUTION_ADMIN: "Institution Admin",
  FACULTY: "Faculty",
  DEPARTMENT_HEAD: "Department Head",
  MCQ: "Multiple choice",
  TECHNICAL: "Written",
  CODING: "Coding",
  // Question source
  COMPANY_PRIVATE: "Your company",
  COMPANY_IMPORT: "Company import",
  COMPANY_MANUAL: "Added by your team",
  AI_GENERATED: "AI generated",
  AI_GENERATED_COMPANY_PRIVATE: "AI generated (private)",
  PLATFORM_APPROVED: "Platform library",
  company_import: "Company import",
  platform_question: "Platform question",
  generated: "AI generated",
  question_bank: "Question bank",
  // Source types (evidence)
  RESUME_CLAIM: "Resume claim (unverified)",
  ASSESSMENT_MCQ: "MCQ assessment",
  ASSESSMENT_TECHNICAL: "Technical assessment",
  ASSESSMENT_CODING: "Coding assessment",
  INTERVIEW_ANSWER: "Interview answer",
  // Execution backend
  judge0: "Code runner",
  local_fallback: "Built-in runner",
};

export function humanize(value: string | null | undefined): string {
  if (!value) return "—";
  if (LABEL_MAP[value]) return LABEL_MAP[value];
  // Only all-caps identifiers are lowercased first, so real names such as "PostgreSQL" keep their casing.
  const base = /^[A-Z0-9_ ]+$/.test(value) ? value.toLowerCase() : value;
  return base.replaceAll("_", " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ─── pct helper ───────────────────────────────────────────────────────────────
/** Display label for a question type identifier (the stored value is unchanged). */
export function questionTypeLabel(t: string | null | undefined): string {
  return ({ MCQ: "Multiple choice", TECHNICAL: "Written", TECHNICAL_WRITTEN: "Written", CODING: "Coding" } as Record<string, string>)[t ?? ""] ?? "Question";
}

export function pct(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined ? "—" : `${(v * 100).toFixed(digits)}%`;
}

// ─── Loading ──────────────────────────────────────────────────────────────────
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-3 text-sm text-gray-500">
      <svg className="animate-spin h-4 w-4 shrink-0 text-gray-400" viewBox="0 0 24 24" fill="none">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z" />
      </svg>
      {label}
    </div>
  );
}

// ─── Skeleton ─────────────────────────────────────────────────────────────────
export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-gray-200 ${className}`} />;
}

export function SkeletonCard() {
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
      <Skeleton className="h-4 w-1/3" />
      <Skeleton className="h-3 w-full" />
      <Skeleton className="h-3 w-4/5" />
    </div>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────
export function Empty({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="py-8 flex flex-col items-center gap-3 text-center">
      <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center">
        <svg className="w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M20 13V6a2 2 0 00-2-2H6a2 2 0 00-2 2v7m16 0v5a2 2 0 01-2 2H6a2 2 0 01-2-2v-5m16 0h-2.586a1 1 0 00-.707.293l-2.414 2.414a1 1 0 01-.707.293h-3.172a1 1 0 01-.707-.293l-2.414-2.414A1 1 0 006.586 13H4" />
        </svg>
      </div>
      <p className="text-sm text-gray-500 max-w-xs">{children}</p>
      {action && <div>{action}</div>}
    </div>
  );
}

// ─── ErrorBox ────────────────────────────────────────────────────────────────
export function ErrorBox({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div
      role="alert"
      className="flex items-start justify-between gap-3 rounded-md border border-red-200 bg-red-50 px-3 py-2.5 text-sm text-red-700"
    >
      <span>{apiError(error)}</span>
      {onRetry && (
        <button
          onClick={onRetry}
          className="shrink-0 rounded text-xs font-medium text-red-700 underline hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400"
        >
          Retry
        </button>
      )}
    </div>
  );
}

// ─── Badge ────────────────────────────────────────────────────────────────────
const TONE_CLS: Record<string, string> = {
  green:  "bg-emerald-50 text-emerald-700 border-emerald-200",
  amber:  "bg-amber-50 text-amber-700 border-amber-200",
  red:    "bg-red-50 text-red-700 border-red-200",
  blue:   "bg-blue-50 text-blue-700 border-blue-200",
  gray:   "bg-gray-100 text-gray-600 border-gray-200",
  purple: "bg-purple-50 text-purple-700 border-purple-200",
};

const STATUS_TONE: Record<string, string> = {
  // Positive / success
  READY: "green", COMPLETED: "green", PUBLISHED: "green", APPROVED: "green",
  ACTIVE: "green", SCORED: "green", SHORTLISTED: "green", OFFER: "green",
  PARSED: "green",
  // Info / in-progress
  VALIDATED: "blue", REQUIREMENTS_CONFIRMED: "blue", ASSESSMENT_READY: "blue",
  APPLIED: "blue", ASSESSMENT_COMPLETED: "blue", INTERVIEW_COMPLETED: "blue",
  SUBMITTED: "blue",
  // Warning / pending
  PROCESSING: "amber", RUNNING: "amber", PENDING: "amber", IN_PROGRESS: "amber",
  SKILLS_EXTRACTED: "amber", ASSESSMENT_PENDING: "amber", INTERVIEW_PENDING: "amber",
  UNDER_REVIEW: "amber", PREPARING: "amber",
  // Neutral
  DRAFT: "gray", CLOSED: "gray", RETIRED: "gray", DISABLED: "gray",
  OPEN_MARKET: "gray", NOT_REQUIRED: "gray", INSTITUTION: "blue",
  // Negative
  FAILED: "red", REJECTED: "red",
  // Source / backend
  local_fallback: "amber", judge0: "green",
};

export function Badge({ children, tone }: { children: ReactNode; tone?: string }) {
  const str = String(children);
  const t = tone ?? STATUS_TONE[str] ?? "gray";
  return (
    <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border font-medium ${TONE_CLS[t] ?? TONE_CLS.gray}`}>
      {humanize(str)}
    </span>
  );
}

// ─── Card ─────────────────────────────────────────────────────────────────────
export function Card({
  title,
  description,
  actions,
  children,
  padding = true,
}: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  padding?: boolean;
}) {
  return (
    <section className="bg-white border border-gray-200 rounded-lg shadow-sm overflow-hidden">
      {(title || actions) && (
        <div className="flex items-start justify-between gap-3 px-4 py-3 border-b border-gray-100">
          <div>
            {title && <h2 className="text-sm font-semibold text-gray-900">{title}</h2>}
            {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
          </div>
          {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
        </div>
      )}
      <div className={padding ? "p-4 space-y-3" : ""}>{children}</div>
    </section>
  );
}

// ─── Button ───────────────────────────────────────────────────────────────────
type BtnVariant = "primary" | "secondary" | "danger" | "ghost";

const BTN_CLS: Record<BtnVariant, string> = {
  primary:
    "bg-blue-700 text-white hover:bg-blue-800 border border-blue-700 shadow-sm",
  secondary:
    "bg-white text-gray-800 border border-gray-300 hover:bg-gray-50 shadow-sm",
  danger:
    "bg-white text-red-700 border border-red-300 hover:bg-red-50",
  ghost:
    "bg-transparent text-gray-600 border border-transparent hover:bg-gray-100",
};

export function Button({
  children,
  onClick,
  disabled,
  variant = "primary",
  type = "button",
  size = "md",
  icon,
}: {
  children: ReactNode;
  onClick?: () => void;
  disabled?: boolean;
  variant?: BtnVariant;
  type?: "button" | "submit";
  size?: "sm" | "md";
  icon?: ReactNode;
}) {
  const sizeCls = size === "sm" ? "text-xs px-2.5 py-1.5" : "text-sm px-3.5 py-2";
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={`inline-flex items-center gap-1.5 rounded-md font-medium transition-colors duration-100 disabled:opacity-50 disabled:cursor-not-allowed focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:outline-none ${sizeCls} ${BTN_CLS[variant]}`}
    >
      {icon && <span className="w-4 h-4 shrink-0">{icon}</span>}
      {children}
    </button>
  );
}

// ─── Input styling constants ──────────────────────────────────────────────────
export const inputCls =
  "w-full rounded-md border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-900 shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100 focus:outline-none transition";

// ─── FormField ───────────────────────────────────────────────────────────────
export function FormField({
  label,
  hint,
  error,
  required,
  children,
  id,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
  id?: string;
}) {
  return (
    <div className="space-y-1">
      <label
        htmlFor={id}
        className="block text-xs font-medium text-gray-700"
      >
        {label}
        {required && <span className="ml-0.5 text-red-500">*</span>}
      </label>
      {children}
      {hint && !error && <p className="text-xs text-gray-400">{hint}</p>}
      {error && <p className="text-xs text-red-600" role="alert">{error}</p>}
    </div>
  );
}

// ─── Table ────────────────────────────────────────────────────────────────────
export function Table({
  head,
  children,
  compact,
}: {
  head: string[];
  children: ReactNode;
  compact?: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-gray-200">
            {head.map((h) => (
              <th
                key={h}
                className={`text-left text-xs font-medium text-gray-500 ${compact ? "py-1.5 pr-3" : "py-2.5 pr-4"}`}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">{children}</tbody>
      </table>
    </div>
  );
}

// ─── Tabs ─────────────────────────────────────────────────────────────────────
export function Tabs<T extends string>({
  tabs,
  current,
  onChange,
  badge,
}: {
  tabs: { id: T; label: string }[];
  current: T;
  onChange: (id: T) => void;
  badge?: Partial<Record<T, number>>;
}) {
  return (
    <div className="flex gap-1 border-b border-gray-200" role="tablist">
      {tabs.map((t) => {
        const active = t.id === current;
        const count = badge?.[t.id];
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(t.id)}
            className={`px-3.5 py-2 text-sm font-medium border-b-2 transition-colors ${
              active
                ? "border-blue-600 text-blue-700"
                : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300"
            }`}
          >
            {t.label}
            {count != null && count > 0 && (
              <span className={`ml-1.5 text-xs rounded-full px-1.5 py-0.5 font-medium ${active ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-600"}`}>
                {count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}

// ─── PageHeader ───────────────────────────────────────────────────────────────
export function PageHeader({
  title,
  description,
  actions,
  back,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  back?: { label: string; href: string };
}) {
  return (
    <div className="flex items-start justify-between gap-4 pb-5 border-b border-gray-200">
      <div>
        {back && (
          <a
            href={back.href}
            className="inline-flex items-center gap-1 text-xs text-gray-500 hover:text-gray-800 mb-2 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
            {back.label}
          </a>
        )}
        <h1 className="text-xl font-semibold text-gray-900 tracking-tight">{title}</h1>
        {description && (
          <p className="text-sm text-gray-500 mt-0.5">{description}</p>
        )}
      </div>
      {actions && (
        <div className="flex items-center gap-2 shrink-0 pt-0.5">{actions}</div>
      )}
    </div>
  );
}

// ─── MetricCard ───────────────────────────────────────────────────────────────
export function MetricCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "default" | "success" | "warning" | "danger" | "info";
}) {
  const toneMap = {
    default: "text-gray-900",
    success: "text-emerald-700",
    warning: "text-amber-700",
    danger: "text-red-700",
    info: "text-blue-700",
  };
  return (
    <div className="bg-white border border-gray-200 rounded-lg p-4 shadow-sm">
      <p className="text-xs text-gray-500 mb-1">{label}</p>
      <p className={`text-2xl font-semibold tabular-nums ${toneMap[tone ?? "default"]}`}>
        {value}
      </p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  );
}

// ─── StatusBadge ──────────────────────────────────────────────────────────────
/** Use for explicit status display; text is always humanized */
export const StatusBadge = Badge;

// ─── Section header ───────────────────────────────────────────────────────────
export function SectionHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: string;
  actions?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div>
        <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
        {description && <p className="text-xs text-gray-500 mt-0.5">{description}</p>}
      </div>
      {actions}
    </div>
  );
}

// ─── Progress bar ─────────────────────────────────────────────────────────────
export function ProgressBar({ value, max, label }: { value: number; max: number; label?: string }) {
  const pctVal = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div>
      {label && (
        <div className="flex justify-between text-xs text-gray-500 mb-1">
          <span>{label}</span>
          <span>{value} / {max}</span>
        </div>
      )}
      <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
        <div
          className="h-full bg-blue-600 rounded-full transition-all duration-300"
          style={{ width: `${pctVal}%` }}
          role="progressbar"
          aria-valuenow={value}
          aria-valuemax={max}
        />
      </div>
    </div>
  );
}

// ─── Modal ────────────────────────────────────────────────────────────────────
export function Modal({
  open,
  onClose,
  title,
  children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
}) {
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="modal-title"
    >
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />
      <div className="relative z-10 w-full max-w-lg max-h-[90vh] flex flex-col bg-white rounded-xl shadow-xl border border-gray-200 overflow-hidden">
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 shrink-0">
          <h2 id="modal-title" className="text-sm font-semibold text-gray-900">
            {title}
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition-colors"
            aria-label="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>
        <div className="p-5 overflow-y-auto">{children}</div>
      </div>
    </div>
  );
}

// ─── Inline status message ────────────────────────────────────────────────────
export function StatusMessage({
  status,
  message,
}: {
  status: "info" | "success" | "warning" | "error";
  message: string;
}) {
  const cls = {
    info: "bg-blue-50 text-blue-700 border-blue-200",
    success: "bg-emerald-50 text-emerald-700 border-emerald-200",
    warning: "bg-amber-50 text-amber-700 border-amber-200",
    error: "bg-red-50 text-red-700 border-red-200",
  }[status];
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${cls}`} role="status">
      {message}
    </div>
  );
}
