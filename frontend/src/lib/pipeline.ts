/** Hiring-pipeline vocabulary shared by the company, student and placement-officer views. Identifiers are stored values;
 *  labels are display only (the UI never shows the identifier). */

export const STAGE_LABEL: Record<string, string> = {
  APTITUDE_ASSESSMENT: "Aptitude Assessment",
  TECHNICAL_ASSESSMENT: "Technical Assessment",
  CODING_ASSESSMENT: "Coding Assessment",
  TECHNICAL_INTERVIEW: "Technical Interview",
  HR_INTERVIEW: "HR Interview",
};

export const ASSESSMENT_STAGES = ["APTITUDE_ASSESSMENT", "TECHNICAL_ASSESSMENT", "CODING_ASSESSMENT"];
export const INTERVIEW_STAGES = ["TECHNICAL_INTERVIEW", "HR_INTERVIEW"];

export const stageLabel = (t?: string | null) => (t ? STAGE_LABEL[t] ?? "Stage" : "Stage");
export const isInterview = (t: string) => INTERVIEW_STAGES.includes(t);

export const STAGE_BLURB: Record<string, string> = {
  APTITUDE_ASSESSMENT: "Timed questions on quantitative, logical and verbal reasoning.",
  TECHNICAL_ASSESSMENT: "Multiple-choice and written questions on the skills this role needs.",
  CODING_ASSESSMENT: "Programming problems that you run against sample tests and then submit.",
  TECHNICAL_INTERVIEW: "A conversation that starts with the basics and goes deeper into the skills that matter for this role.",
  HR_INTERVIEW: "A short conversation about how you work, what motivates you and your availability. Nothing in it is scored.",
};

export const HR_CATEGORY_LABEL: Record<string, string> = {
  communication: "Communication",
  collaboration: "Team collaboration",
  "conflict handling": "Conflict handling",
  motivation: "Motivation for the role",
  "career goals": "Career goals",
  "work preferences": "Work preferences",
  "availability and logistics": "Availability and logistics",
};

export const APTITUDE_CATEGORIES = ["Quantitative Aptitude", "Logical Reasoning", "Analytical Reasoning", "Data Interpretation", "Verbal Ability"];
export const CODING_LANGUAGES: [string, string][] = [["python", "Python"], ["javascript", "JavaScript"], ["cpp", "C++"]];

export type JourneyStage = {
  stage_id: string;
  stage_type: string;
  label: string;
  order: number;
  status: "LOCKED" | "AVAILABLE" | "IN_PROGRESS" | "COMPLETED" | "SKIPPED";
  kind: "assessment" | "interview";
  started_at?: string | null;
  completed_at?: string | null;
  duration_minutes?: number | null;
  required?: boolean;
  proctored?: boolean;
  assessment_id?: string | null;
  result?: any;
};

/** "Coding Assessment available", "Technical Interview ready", "HR Interview in progress"; null when nothing is waiting on the candidate. */
export function pendingAction(a: { next_stage?: string | null; next_stage_label?: string | null; next_stage_status?: string | null }): string | null {
  if (!a.next_stage || !a.next_stage_label) return null;
  if (a.next_stage_status === "IN_PROGRESS") return `${a.next_stage_label} in progress`;
  return `${a.next_stage_label} ${isInterview(a.next_stage) ? "ready" : "available"}`;
}
