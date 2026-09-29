import { type ReactNode } from "react";
import { EMPLOYMENT_TYPES, WORK_MODES, isInternship, problems, type PostingForm } from "../lib/posting";
import { inputCls } from "./ui";

const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <fieldset className="space-y-2 border-t border-gray-100 pt-3 first:border-0 first:pt-0"><legend className="text-xs font-semibold text-gray-700 mb-1">{title}</legend>{children}</fieldset>
);
const Field = ({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) => (
  <label className="block text-xs text-gray-600 space-y-1"><span>{label}</span>{children}{hint && <span className="block text-[11px] text-gray-400">{hint}</span>}</label>
);
const CURRENCIES = ["INR", "USD", "EUR", "GBP"];

/** Sectioned, conditional posting form. `lockedExceptDeadline` is used after publishing. */
export function PostingFormFields({ f, set, showTitle, lockedExceptDeadline }: {
  f: PostingForm; set: (patch: Partial<PostingForm>) => void; showTitle?: boolean; lockedExceptDeadline?: boolean;
}) {
  const intern = isInternship(f.employment_type);
  const dis = !!lockedExceptDeadline;
  const lpaAvailable = f.currency === "INR" && (f.comp_period || (intern ? "MONTH" : "YEAR")) === "YEAR";
  const errs = problems(f);
  const on = (k: keyof PostingForm) => (e: { target: { value: string } }) => set({ [k]: e.target.value } as Partial<PostingForm>);
  return (
    <div className="space-y-4 text-sm" data-testid="posting-form">
      {showTitle && (
        <Section title="Basic information">
          <Field label="Job title *"><input className={inputCls} value={f.title} onChange={on("title")} data-testid="pf-title" placeholder="e.g. Software Engineer" /></Field>
        </Section>
      )}
      <Section title="Role details">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Experience">
            <select className={inputCls} value={f.exp_level} onChange={on("exp_level")} disabled={dis} data-testid="pf-exp-level">
              <option value="">Not specified</option><option value="FRESHER">Fresher</option><option value="EXPERIENCED">Experienced</option></select></Field>
          {f.exp_level === "EXPERIENCED" && <>
            <Field label="Min years"><input className={inputCls} type="number" min={0} value={f.exp_min} onChange={on("exp_min")} disabled={dis} /></Field>
            <Field label="Max years"><input className={inputCls} type="number" min={0} value={f.exp_max} onChange={on("exp_max")} disabled={dis} /></Field></>}
          <Field label="Openings"><input className={inputCls} type="number" min={1} value={f.openings} onChange={on("openings")} data-testid="pf-openings" placeholder="optional" /></Field>
        </div>
      </Section>
      <Section title="Employment & location">
        <div className="grid grid-cols-2 gap-2">
          <Field label="Employment type *"><select className={inputCls} value={f.employment_type} onChange={on("employment_type")} disabled={dis} data-testid="pf-type">
            <option value="">Select…</option>{EMPLOYMENT_TYPES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Work mode *"><select className={inputCls} value={f.work_mode} onChange={on("work_mode")} disabled={dis} data-testid="pf-mode">
            <option value="">Select…</option>{WORK_MODES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
        </div>
        {f.work_mode && (
          <div className="grid grid-cols-3 gap-2">
            <Field label={f.work_mode === "REMOTE" ? "City (optional)" : "City *"}><input className={inputCls} value={f.city} onChange={on("city")} disabled={dis} data-testid="pf-city" /></Field>
            <Field label="State / region"><input className={inputCls} value={f.state} onChange={on("state")} disabled={dis} /></Field>
            <Field label={f.work_mode === "REMOTE" ? "Country (optional)" : "Country *"}><input className={inputCls} value={f.country} onChange={on("country")} disabled={dis} data-testid="pf-country" /></Field>
          </div>)}
      </Section>
      {f.employment_type && (
        <Section title={intern ? "Stipend" : "Compensation"}>
          <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={f.unpaid} onChange={(e) => set({ unpaid: e.target.checked })} disabled={dis} /> Unpaid</label>
          {!f.unpaid && (
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              <Field label="Currency"><select className={inputCls} value={f.currency} onChange={on("currency")} disabled={dis} data-testid="pf-currency">{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</select></Field>
              <Field label="Per"><select className={inputCls} value={f.comp_period || (intern ? "MONTH" : "YEAR")} onChange={on("comp_period")} disabled={dis} data-testid="pf-period">
                <option value="YEAR">Year</option><option value="MONTH">Month</option><option value="HOUR">Hour</option><option value="FIXED">Fixed</option></select></Field>
              {!intern && <Field label="Type"><select className={inputCls} value={f.comp_type || "SALARY"} onChange={on("comp_type")} disabled={dis}>
                <option value="SALARY">Salary</option><option value="CTC">CTC</option><option value="HOURLY">Hourly</option></select></Field>}
              {lpaAvailable && <Field label="Enter as"><select className={inputCls} value={f.comp_unit} onChange={on("comp_unit")} disabled={dis} data-testid="pf-unit"><option value="LPA">LPA (lakh ₹/year)</option><option value="ABSOLUTE">Absolute ₹/year</option></select></Field>}
              <Field label={lpaAvailable && f.comp_unit === "LPA" ? "Minimum (LPA)" : "Minimum"}><input className={inputCls} type="number" min={0} step="any" value={f.comp_min} onChange={on("comp_min")} disabled={dis} data-testid="pf-min" /></Field>
              <Field label={lpaAvailable && f.comp_unit === "LPA" ? "Maximum (LPA)" : "Maximum"}><input className={inputCls} type="number" min={0} step="any" value={f.comp_max} onChange={on("comp_max")} disabled={dis} data-testid="pf-max" /></Field>
            </div>)}
        </Section>)}
      {intern && (
        <Section title="Internship details">
          <div className="grid grid-cols-3 gap-2">
            <Field label="Duration *"><input className={inputCls} type="number" min={1} value={f.dur_value} onChange={on("dur_value")} disabled={dis} data-testid="pf-dur" /></Field>
            <Field label="Unit"><select className={inputCls} value={f.dur_unit} onChange={on("dur_unit")} disabled={dis} data-testid="pf-dur-unit"><option value="MONTH">Months</option><option value="WEEK">Weeks</option></select></Field>
          </div>
          {f.employment_type === "INTERNSHIP_TO_FULL_TIME" && (
            <div className="space-y-2" data-testid="conversion-section">
              <p className="text-xs text-gray-500">Potential full-time conversion after the internship.</p>
              <div className="grid grid-cols-3 gap-2">
                <Field label={f.ft_unit === "LPA" && f.currency === "INR" ? "Full-time package min (LPA)" : "Full-time package min (per year)"}><input className={inputCls} type="number" min={0} step="any" value={f.ft_min} onChange={on("ft_min")} disabled={dis} data-testid="pf-ft-min" /></Field>
                <Field label={f.ft_unit === "LPA" && f.currency === "INR" ? "Full-time package max (LPA)" : "Full-time package max (per year)"}><input className={inputCls} type="number" min={0} step="any" value={f.ft_max} onChange={on("ft_max")} disabled={dis} data-testid="pf-ft-max" /></Field>
                {f.currency === "INR" && <Field label="Enter as"><select className={inputCls} value={f.ft_unit} onChange={on("ft_unit")} disabled={dis}><option value="LPA">LPA</option><option value="ABSOLUTE">Absolute ₹/year</option></select></Field>}
              </div>
              <Field label="Conversion notes"><input className={inputCls} value={f.conv_notes} onChange={on("conv_notes")} disabled={dis} data-testid="pf-conv-notes" placeholder="e.g. Based on internship performance review" /></Field>
              <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={f.conv_guaranteed} onChange={(e) => set({ conv_guaranteed: e.target.checked })} disabled={dis} /> Conversion is guaranteed (leave unchecked unless you commit to it)</label>
            </div>)}
        </Section>)}
      <Section title="Application details">
        <Field label="Applications close" hint="Students cannot apply after this time. You can extend it later, even after publishing.">
          <input className={inputCls} type="datetime-local" value={f.deadline} onChange={on("deadline")} data-testid="pf-deadline" /></Field>
      </Section>
      {errs.length > 0 && <ul className="text-xs text-red-600 list-disc pl-4" data-testid="pf-errors">{errs.map((e) => <li key={e}>{e}</li>)}</ul>}
    </div>
  );
}
