// Job posting vocabulary and client-side rules. The server (services/jobs/posting.py) is authoritative; these mirror it so the form
// can explain problems before submitting. Identifiers are machine values; labels are display only.
export const EMPLOYMENT_TYPES = [
  ["FULL_TIME", "Full-time"], ["INTERNSHIP", "Internship"], ["INTERNSHIP_TO_FULL_TIME", "Internship → Full-time"],
  ["PART_TIME", "Part-time"], ["CONTRACT", "Contract"],
] as const;
export const WORK_MODES = [["ONSITE", "On-site"], ["HYBRID", "Hybrid"], ["REMOTE", "Remote"]] as const;
export const isInternship = (t: string) => t === "INTERNSHIP" || t === "INTERNSHIP_TO_FULL_TIME";
export const label = (list: readonly (readonly [string, string])[], v?: string | null) => list.find(([k]) => k === v)?.[1];

export type PostingForm = {
  title: string; employment_type: string; work_mode: string; city: string; state: string; country: string;
  exp_level: string; exp_min: string; exp_max: string; openings: string; deadline: string;
  currency: string; comp_type: string; comp_period: string; comp_unit: "LPA" | "ABSOLUTE"; comp_min: string; comp_max: string; unpaid: boolean;
  dur_value: string; dur_unit: string; conv_guaranteed: boolean; conv_notes: string; ft_min: string; ft_max: string; ft_unit: "LPA" | "ABSOLUTE";
};

export const emptyPosting = (): PostingForm => ({
  title: "", employment_type: "", work_mode: "", city: "", state: "", country: "", exp_level: "", exp_min: "", exp_max: "", openings: "", deadline: "",
  currency: "INR", comp_type: "", comp_period: "", comp_unit: "LPA", comp_min: "", comp_max: "", unpaid: false,
  dur_value: "", dur_unit: "MONTH", conv_guaranteed: false, conv_notes: "", ft_min: "", ft_max: "", ft_unit: "LPA",
});

const num = (s: string) => (s.trim() === "" ? null : Number(s));

/** Absolute amount (string from the API) -> the form's entry value, using LPA for whole-lakh INR yearly amounts. */
function fromAbs(v: string | null | undefined, currency: string, period: string): { text: string; unit: "LPA" | "ABSOLUTE" } {
  if (v == null) return { text: "", unit: currency === "INR" && period === "YEAR" ? "LPA" : "ABSOLUTE" };
  const n = Number(v);
  if (currency === "INR" && period === "YEAR" && n >= 100000) return { text: String(n / 100000), unit: "LPA" };
  return { text: String(n), unit: "ABSOLUTE" };
}

export function fromJob(j: any): PostingForm {
  const f = emptyPosting();
  const cur = j.compensation_currency ?? "INR";
  const lo = fromAbs(j.compensation_min, cur, j.compensation_period ?? "");
  const hi = fromAbs(j.compensation_max, cur, j.compensation_period ?? "");
  const ft0 = fromAbs(j.full_time_compensation_min, cur, "YEAR");
  const ft1 = fromAbs(j.full_time_compensation_max, cur, "YEAR");
  return {
    ...f, title: j.title ?? "", employment_type: j.employment_type ?? "", work_mode: j.work_mode ?? "", city: j.location_city ?? "", state: j.location_state ?? "",
    country: j.location_country ?? "", exp_level: j.experience_level ?? "", exp_min: j.experience_min_years?.toString() ?? "", exp_max: j.experience_max_years?.toString() ?? "",
    openings: j.number_of_openings?.toString() ?? "", deadline: j.application_deadline ? toLocalInput(j.application_deadline) : "", currency: cur,
    comp_type: j.compensation_type ?? "", comp_period: j.compensation_period ?? "", comp_unit: lo.unit === "LPA" && hi.unit !== "ABSOLUTE" ? "LPA" : lo.unit,
    comp_min: lo.text, comp_max: hi.text, unpaid: j.compensation_type === "UNPAID", dur_value: j.internship_duration_value?.toString() ?? "",
    dur_unit: j.internship_duration_unit ?? "MONTH", conv_guaranteed: !!j.conversion_guaranteed, conv_notes: j.conversion_notes ?? "",
    ft_min: ft0.text, ft_max: ft1.text, ft_unit: ft0.unit === "ABSOLUTE" ? "ABSOLUTE" : "LPA",
  };
}

const toLocalInput = (iso: string) => { const d = new Date(iso); const p = (n: number) => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`; };

/** Client-side problems, in the same words as the server. Empty list = OK to submit. */
export function problems(f: PostingForm): string[] {
  const p: string[] = [];
  const intern = isInternship(f.employment_type);
  if (intern && (!f.dur_value || Number(f.dur_value) < 1)) p.push("Internships need a duration");
  if ((f.work_mode === "ONSITE" || f.work_mode === "HYBRID") && (!f.city.trim() || !f.country.trim())) p.push("On-site and hybrid roles need a city and country");
  if (f.exp_level === "EXPERIENCED" && f.exp_min && f.exp_max && Number(f.exp_min) > Number(f.exp_max)) p.push("Minimum experience cannot exceed the maximum");
  if (f.openings && Number(f.openings) < 1) p.push("Number of openings must be at least 1");
  if (!f.unpaid && f.comp_min && f.comp_max && Number(f.comp_min) > Number(f.comp_max)) p.push("Minimum compensation cannot exceed the maximum");
  if (f.employment_type === "INTERNSHIP_TO_FULL_TIME" && f.ft_min && f.ft_max && Number(f.ft_min) > Number(f.ft_max)) p.push("Full-time package minimum cannot exceed the maximum");
  if (f.conv_guaranteed && !f.conv_notes.trim()) p.push("Explain the conversion guarantee in the conversion notes");
  if (f.deadline && new Date(f.deadline).getTime() <= Date.now()) p.push("The application deadline must be in the future");
  return p;
}

export function toPayload(f: PostingForm, withTitle = false) {
  const intern = isInternship(f.employment_type);
  const hasComp = !f.unpaid && (f.comp_min.trim() !== "" || f.comp_max.trim() !== "");
  const lpaOk = f.currency === "INR" && (f.comp_period || (intern ? "MONTH" : "YEAR")) === "YEAR";
  const ftHas = f.employment_type === "INTERNSHIP_TO_FULL_TIME" && (f.ft_min.trim() !== "" || f.ft_max.trim() !== "");
  return {
    ...(withTitle ? { title: f.title.trim() } : {}),
    employment_type: f.employment_type || null, work_mode: f.work_mode || null,
    location_city: f.city.trim() || null, location_state: f.state.trim() || null, location_country: f.country.trim() || null,
    experience_level: f.exp_level || null, experience_min_years: f.exp_level === "EXPERIENCED" ? num(f.exp_min) : null,
    experience_max_years: f.exp_level === "EXPERIENCED" ? num(f.exp_max) : null,
    number_of_openings: num(f.openings), application_deadline: f.deadline ? new Date(f.deadline).toISOString() : null,
    compensation_currency: f.unpaid ? null : hasComp ? f.currency : null,
    compensation_min: hasComp ? num(f.comp_min) : null, compensation_max: hasComp ? num(f.comp_max) : null,
    compensation_period: f.unpaid ? null : hasComp ? f.comp_period || (intern ? "MONTH" : "YEAR") : null,
    compensation_type: f.unpaid ? "UNPAID" : hasComp ? (intern ? "STIPEND" : f.comp_type || "SALARY") : null,
    compensation_input_unit: hasComp && f.comp_unit === "LPA" && lpaOk ? "LPA" : "ABSOLUTE",
    internship_duration_value: intern ? num(f.dur_value) : null, internship_duration_unit: intern ? f.dur_unit : null,
    conversion_guaranteed: f.employment_type === "INTERNSHIP_TO_FULL_TIME" ? f.conv_guaranteed : false,
    conversion_notes: f.employment_type === "INTERNSHIP_TO_FULL_TIME" ? f.conv_notes.trim() || null : null,
    full_time_compensation_min: ftHas ? num(f.ft_min) : null, full_time_compensation_max: ftHas ? num(f.ft_max) : null,
    full_time_input_unit: ftHas && f.currency === "INR" && f.ft_unit === "LPA" ? "LPA" : "ABSOLUTE",
  };
}
