import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, humanize, inputCls, questionTypeLabel } from "../../components/ui";
import {
  APTITUDE_CATEGORIES,
  CODING_LANGUAGES,
  COMPONENT_LABEL,
  HR_CATEGORY_LABEL,
  STAGE_BLURB,
  isInterview,
} from "../../lib/pipeline";

type StageView = {
  id: string;
  stage_type: string;
  label: string;
  enabled: boolean;
  required: boolean;
  duration_minutes: number | null;
  question_count: number | null;
  proctored: boolean;
  status: string;
  config: any;
  assessment_id: string | null;
  group: "assessment" | "interview";
  readiness: { state: string; detail: string; questions?: number };
  pass_threshold: number | null;
  auto_qualify: boolean;
  weights: Record<string, number> | null;
  weight_components: string[];
  default_weights: Record<string, number> | null;
};

const DOMAIN_OF: Record<string, string | null> = {
  APTITUDE_ASSESSMENT: "APTITUDE",
  TECHNICAL_ASSESSMENT: "TECHNICAL",
  CODING_ASSESSMENT: null,
  TECHNICAL_INTERVIEW: "TECHNICAL_INTERVIEW",
  HR_INTERVIEW: "HR_INTERVIEW",
};
const HR_CATEGORIES = Object.keys(HR_CATEGORY_LABEL);
const DIFFS: [string, string][] = [["easy", "Easy"], ["medium", "Medium"], ["hard", "Hard"]];

/** What to show for a stage right now: unsaved local changes (enabled but not yet saved) must not still read "Disabled". */
function displayState(s: StageView, dirty: boolean, published: boolean, generating: boolean): string {
  if (generating) return "PREPARING";
  if (!s.enabled) return "DISABLED";
  if (dirty && !published && s.readiness.state === "DISABLED") return "NEEDS_CONFIGURATION";
  return s.readiness.state;
}
function displayDetail(s: StageView, dirty: boolean): string {
  if (s.readiness.state === "DISABLED" && s.enabled) return dirty ? "Save the hiring process, then prepare this stage" : s.readiness.detail;
  return s.readiness.detail;
}

const toPayload = (s: StageView) => ({
  stage_type: s.stage_type,
  enabled: s.enabled,
  required: s.required,
  duration_minutes: s.duration_minutes,
  question_count: s.question_count,
  proctored: s.proctored,
  config: s.config,
  pass_threshold: s.pass_threshold,
  auto_qualify: s.auto_qualify,
  weights: s.weights,
});

function num(v: string): number | null {
  const n = Number(v);
  return v.trim() === "" || Number.isNaN(n) ? null : n;
}

function Labeled({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs space-y-1">
      <span className="font-medium text-gray-700">{label}</span>
      {children}
      {hint && <span className="block text-gray-400">{hint}</span>}
    </label>
  );
}

function PercentMix({ value, keys, onChange, labels }: { value: Record<string, number>; keys: string[]; onChange: (v: Record<string, number>) => void; labels?: Record<string, string> }) {
  const total = Object.values(value).reduce((a, b) => a + (Number(b) || 0), 0);
  return (
    <div className="space-y-1.5">
      {keys.map((k) => {
        const on = k in value;
        return (
          <div key={k} className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              id={`mix-${k}`}
              checked={on}
              onChange={(e) => {
                const next = { ...value };
                if (e.target.checked) next[k] = 0;
                else delete next[k];
                onChange(next);
              }}
            />
            <label htmlFor={`mix-${k}`} className="w-44 text-gray-700">{labels?.[k] ?? k}</label>
            {on && (
              <>
                <input
                  aria-label={`${labels?.[k] ?? k} percentage`}
                  className={inputCls}
                  style={{ width: "5rem" }}
                  type="number"
                  min={0}
                  max={100}
                  value={value[k]}
                  onChange={(e) => onChange({ ...value, [k]: Number(e.target.value) })}
                />
                <span className="text-gray-400">%</span>
              </>
            )}
          </div>
        );
      })}
      <p className={`text-xs ${Math.abs(total - 100) <= 1.5 ? "text-emerald-700" : "text-amber-700"}`}>Total: {total}%{Math.abs(total - 100) <= 1.5 ? "" : " — must add up to 100%"}</p>
    </div>
  );
}

function StageSettings({ stage, skills, disabled, update }: { stage: StageView; skills: any[]; disabled: boolean; update: (patch: Partial<StageView>) => void }) {
  const cfg = stage.config ?? {};
  const setCfg = (patch: any) => update({ config: { ...cfg, ...patch } });
  const t = stage.stage_type;
  const interview = isInterview(t);
  return (
    <fieldset disabled={disabled} className="space-y-4 min-w-0">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {t === "TECHNICAL_INTERVIEW" ? (
          <Labeled label="Interview length" hint={`About ${Math.max(6, Math.min(10, Math.round((stage.duration_minutes ?? 45) / 5)))} substantive questions`}>
            <select className={inputCls} value={stage.duration_minutes ?? 45} onChange={(e) => update({ duration_minutes: Number(e.target.value), question_count: null })} data-testid="ti-duration">
              {[30, 45, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}
            </select>
          </Labeled>
        ) : (
          <Labeled label="Time limit (minutes)" hint={interview ? "Planned length" : "The timer starts when the candidate begins this stage"}>
            <input className={inputCls} type="number" min={5} max={180} value={stage.duration_minutes ?? ""} onChange={(e) => update({ duration_minutes: num(e.target.value) })} data-testid="stage-duration" />
          </Labeled>
        )}
        {t !== "TECHNICAL_INTERVIEW" && (
          <Labeled label={t === "CODING_ASSESSMENT" ? "Number of coding problems" : "Number of questions"} hint={t === "CODING_ASSESSMENT" ? "1 to 5" : t === "HR_INTERVIEW" ? "Between 3 and 10; 5 to 8 works well" : undefined}>
            <input className={inputCls} type="number" min={1} max={t === "CODING_ASSESSMENT" ? 5 : 60} value={stage.question_count ?? ""} onChange={(e) => update({ question_count: num(e.target.value) })} data-testid="stage-count" />
          </Labeled>
        )}
        <Labeled label="Monitoring">
          <span className="flex items-center gap-2 text-gray-700 py-1.5">
            <input type="checkbox" checked={stage.proctored} onChange={(e) => update({ proctored: e.target.checked })} />
            {interview ? "Camera and microphone check" : "Proctored (camera, microphone, fullscreen)"}
          </span>
        </Labeled>
      </div>

      {t === "APTITUDE_ASSESSMENT" && (
        <>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-700">Categories</p>
            <PercentMix value={cfg.categories ?? {}} keys={APTITUDE_CATEGORIES} onChange={(v) => setCfg({ categories: v })} />
          </div>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-700">Difficulty mix</p>
            <PercentMix value={cfg.difficulty ?? {}} keys={DIFFS.map(([k]) => k)} labels={Object.fromEntries(DIFFS)} onChange={(v) => setCfg({ difficulty: v })} />
          </div>
        </>
      )}

      {t === "TECHNICAL_ASSESSMENT" && (
        <>
          <Labeled label="Multiple-choice share (%)" hint="The rest are written questions. Coding problems belong to the Coding Assessment.">
            <input className={`${inputCls} w-28`} type="number" min={0} max={100} value={cfg.mcq_share ?? 40} onChange={(e) => setCfg({ mcq_share: Number(e.target.value) })} />
          </Labeled>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-700">Difficulty mix</p>
            <PercentMix value={cfg.difficulty ?? {}} keys={DIFFS.map(([k]) => k)} labels={Object.fromEntries(DIFFS)} onChange={(v) => setCfg({ difficulty: v })} />
          </div>
        </>
      )}

      {t === "CODING_ASSESSMENT" && (
        <>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-700">Allowed languages</p>
            <div className="flex flex-wrap gap-4 text-xs">
              {CODING_LANGUAGES.map(([id, name]) => (
                <label key={id} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={(cfg.languages ?? []).includes(id)}
                    onChange={(e) => setCfg({ languages: e.target.checked ? [...(cfg.languages ?? []), id] : (cfg.languages ?? []).filter((x: string) => x !== id) })}
                  />
                  {name}
                </label>
              ))}
            </div>
          </div>
          <Labeled label="Difficulty">
            <select className={`${inputCls} w-40`} value={cfg.difficulty ?? "medium"} onChange={(e) => setCfg({ difficulty: e.target.value })}>
              {DIFFS.map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
          </Labeled>
          <p className="text-xs text-gray-500">Every problem has visible sample tests and hidden tests, and its reference solution is verified in the code runner before it is used. Correctness is decided by the tests only.</p>
        </>
      )}

      {(t === "TECHNICAL_ASSESSMENT" || t === "CODING_ASSESSMENT") && skills.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-gray-700">Skills covered <span className="font-normal text-gray-400">(none selected = every confirmed requirement)</span></p>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
            {skills.map((s: any) => (
              <label key={s.skill_id} className="flex items-center gap-1.5">
                <input
                  type="checkbox"
                  checked={(cfg.skill_ids ?? []).includes(s.skill_id)}
                  onChange={(e) => setCfg({ skill_ids: e.target.checked ? [...(cfg.skill_ids ?? []), s.skill_id] : (cfg.skill_ids ?? []).filter((x: string) => x !== s.skill_id) })}
                />
                {s.canonical_name ?? s.raw_skill_name}
              </label>
            ))}
          </div>
        </div>
      )}

      {t === "HR_INTERVIEW" && (
        <>
          <div className="space-y-1.5">
            <p className="text-xs font-medium text-gray-700">Topics</p>
            <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
              {HR_CATEGORIES.map((c) => (
                <label key={c} className="flex items-center gap-1.5">
                  <input
                    type="checkbox"
                    checked={(cfg.categories ?? []).includes(c)}
                    onChange={(e) => setCfg({ categories: e.target.checked ? [...(cfg.categories ?? []), c] : (cfg.categories ?? []).filter((x: string) => x !== c) })}
                  />
                  {HR_CATEGORY_LABEL[c]}
                </label>
              ))}
            </div>
          </div>
          <p className="text-xs text-gray-500 rounded-md bg-gray-50 border border-gray-200 p-2.5">
            Questions are job-relevant only. Protected and sensitive topics (religion, family plans, health, age and similar) are never asked, and this stage records neutral notes for a reviewer: it produces no score, personality rating or fit percentage.
          </p>
        </>
      )}
    </fieldset>
  );
}

/** Qualification requirement for a round. Before publishing it is part of the hiring-process draft; after publishing it saves on its own
 *  (round content is frozen, the requirement is not) and applies to candidates who finish the round from then on. */
function QualificationSettings({ job, stage, nextLabel, published, update }: { job: any; stage: StageView; nextLabel: string; published: boolean; update: (p: Partial<StageView>) => void }) {
  const qc = useQueryClient();
  const [local, setLocal] = useState({ t: stage.pass_threshold, auto: stage.auto_qualify, w: stage.weights });
  const t = published ? local.t : stage.pass_threshold;
  const auto = published ? local.auto : stage.auto_qualify;
  const w = (published ? local.w : stage.weights) ?? null;
  const comps = stage.weight_components;
  const set = (p: { t?: number | null; auto?: boolean; w?: Record<string, number> | null }) => {
    if (published) setLocal((l) => ({ t: "t" in p ? p.t! : l.t, auto: p.auto ?? l.auto, w: "w" in p ? p.w! : l.w }));
    else update({ ...("t" in p ? { pass_threshold: p.t } : {}), ...(p.auto !== undefined ? { auto_qualify: p.auto } : {}), ...("w" in p ? { weights: p.w } : {}) });
  };
  const save = useMutation({
    mutationFn: () => api.put(`/hiring-pipeline/jobs/${job.id}/qualification`, { stages: [{ stage_type: stage.stage_type, pass_threshold: local.t, auto_qualify: local.auto, weights: local.w }] }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["pipeline-config", job.id] }),
  });
  const effW = w ?? stage.default_weights;
  const total = effW ? Object.values(effW).reduce((a, b) => a + (Number(b) || 0), 0) : 0;
  const bad = t != null && (Number.isNaN(t) || t < 0 || t > 100);
  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-gray-50/60 p-4" data-testid="qualification-settings">
      <div>
        <p className="text-sm font-semibold text-gray-900">Qualification</p>
        <p className="text-xs text-gray-500">A candidate moves on only when their finished score for this round is at or above the pass threshold. The score is computed by fixed rules, never decided by an AI model.</p>
      </div>
      <div className="flex flex-wrap items-end gap-4">
        <label className="block text-xs space-y-1">
          <span className="font-medium text-gray-700">Pass threshold</span>
          <span className="flex items-center gap-1.5">
            <input
              className={inputCls}
              style={{ width: "5.5rem" }}
              type="number"
              min={0}
              max={100}
              placeholder="e.g. 70"
              value={t ?? ""}
              onChange={(e) => set({ t: e.target.value === "" ? null : Number(e.target.value) })}
              data-testid="pass-threshold"
              aria-invalid={bad}
            />
            <span className="text-gray-500">% (0 to 100)</span>
          </span>
        </label>
        <label className="flex items-center gap-2 text-xs text-gray-700 pb-2">
          <input type="checkbox" checked={!!auto} disabled={t == null} onChange={(e) => set({ auto: e.target.checked })} data-testid="auto-qualify" />
          Automatically qualify candidates who meet this score
        </label>
      </div>
      {bad && <p className="text-xs text-red-700">The threshold must be a number from 0 to 100.</p>}
      {t == null && <p className="text-xs text-gray-500">No threshold: candidates who finish this round move straight to the next one.</p>}
      {t != null && !auto && <p className="text-xs text-amber-800">Automatic qualification is off: after this round a person decides whether the candidate moves on.</p>}
      {comps.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-xs font-medium text-gray-700">How the round score is made up {stage.default_weights && !w ? "(default weights shown)" : ""}</p>
          <div className="flex flex-wrap gap-3">
            {comps.map((c) => (
              <label key={c} className="text-xs space-y-1">
                <span className="text-gray-600">{COMPONENT_LABEL[c] ?? c}</span>
                <span className="flex items-center gap-1">
                  <input className={inputCls} style={{ width: "4.5rem" }} type="number" min={0} max={100} value={effW?.[c] ?? ""} placeholder="—"
                    onChange={(e) => set({ w: { ...(effW ?? {}), [c]: e.target.value === "" ? 0 : Number(e.target.value) } })} aria-label={`${COMPONENT_LABEL[c] ?? c} weight`} />
                  <span className="text-gray-400">%</span>
                </span>
              </label>
            ))}
          </div>
          <p className={`text-xs ${!effW || Math.abs(total - 100) <= 0.5 ? "text-gray-500" : "text-amber-700"}`}>
            {effW ? `Weights total ${total}%${Math.abs(total - 100) <= 0.5 ? "" : ": they must add up to 100%"}.` : "Without weights the score is the round's own points-weighted result."}
            {" "}
            {w && <button type="button" className="text-blue-700 hover:underline" onClick={() => set({ w: null })}>Use default scoring</button>}
          </p>
        </div>
      )}
      <p className="text-xs text-gray-600">Next round: <b>{nextLabel}</b></p>
      {published && (
        <div className="flex items-center gap-3">
          <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || bad} data-testid="save-qualification">Save qualification settings</Button>
          <span className="text-xs text-gray-500">Applies to candidates who finish this round from now on; earlier results keep the threshold they were judged by.</span>
          {save.isSuccess && <span className="text-xs font-medium text-emerald-700">✓ Saved</span>}
        </div>
      )}
      <ErrorBox error={save.error} />
    </div>
  );
}

function AssessmentContent({ stage }: { stage: StageView }) {
  const detail = useQuery({
    queryKey: ["assessment-detail", stage.assessment_id],
    enabled: !!stage.assessment_id,
    queryFn: () => api.get(`/assessments/${stage.assessment_id}`).then((r) => r.data),
  });
  if (!stage.assessment_id) return <Empty>No questions yet. Save your settings, then generate this stage.</Empty>;
  if (detail.isLoading) return <Loading />;
  const plan = detail.data?.plan;
  const questions = (detail.data?.sections ?? []).flatMap((s: any) => s.questions.map((q: any) => ({ ...q.question, section: s.title })));
  return (
    <div className="space-y-3" data-testid="stage-content">
      {plan && (
        <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-gray-600">
          <span><b>{plan.covered_slots ?? questions.length}</b> questions ready</span>
          {plan.missing_slots > 0 && <span className="text-amber-700 font-medium">{plan.missing_slots} still uncovered</span>}
          <span>{plan.reused_company ?? 0} from your private bank</span>
          <span>{plan.reused_platform ?? 0} from approved platform questions</span>
          <span>{plan.generated ?? 0} newly generated</span>
        </div>
      )}
      {plan?.uncovered?.length > 0 && <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">Could not fill: {plan.uncovered.join(", ")}. Add questions to your private bank or generate again.</p>}
      {questions.length > 0 && (
        <Table head={[stage.stage_type === "APTITUDE_ASSESSMENT" ? "Category" : "Skill", "Type", "Difficulty", "Source", "Question"]}>
          {questions.map((q: any) => (
            <tr key={q.id} className="align-top">
              <td className="py-2 pr-3 font-medium text-gray-900 whitespace-nowrap">{q.section}</td>
              <td className="pr-3"><Badge tone="gray">{questionTypeLabel(q.question_type)}</Badge></td>
              <td className="pr-3 text-xs text-gray-600">{humanize(q.difficulty)}</td>
              <td className="pr-3 text-xs text-gray-600">{humanize(q.source_type)}</td>
              <td className="pr-3 text-xs text-gray-700 leading-relaxed max-w-md">{q.question_text}</td>
            </tr>
          ))}
        </Table>
      )}
    </div>
  );
}

function InterviewContent({ job, stage, published }: { job: any; stage: StageView; published: boolean }) {
  const qc = useQueryClient();
  const tpl = useQuery({
    queryKey: ["interview-template", job.id, stage.stage_type],
    refetchInterval: (q) => (q.state.data?.status === "PREPARING" ? 3000 : false),
    queryFn: () => api.get(`/interviews/templates/by-job/${job.id}`, { params: { stage_type: stage.stage_type } }).then((r) => r.data),
  });
  const rebuild = useMutation({
    mutationFn: () => api.post(`/interviews/templates/by-job/${job.id}/rebuild`, null, { params: { stage_type: stage.stage_type } }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["interview-template", job.id] });
      qc.invalidateQueries({ queryKey: ["pipeline-config", job.id] });
    },
  });
  if (tpl.isLoading) return <Loading />;
  const t = tpl.data;
  if (!t) return <Empty>The interview plan has not been prepared yet. Save your settings, then prepare this stage.</Empty>;
  const cfg = t.config ?? {};
  const bp: any[] = cfg.blueprint ?? [];
  const byComp: Record<string, any[]> = {};
  (t.questions ?? []).forEach((q: any) => (byComp[q.skill ?? "—"] = [...(byComp[q.skill ?? "—"] ?? []), q]));
  return (
    <div className="space-y-3 text-xs" data-testid="interview-plan">
      <div className="flex flex-wrap items-center gap-3">
        <Badge>{t.status}</Badge>
        <span className="text-gray-600">Planned length: {cfg.min_questions}–{cfg.max_questions} questions (~{cfg.recommended_minutes} min). Every candidate is evaluated against the same blueprint and rubric.</span>
      </div>
      {t.status === "FAILED" && <p className="text-red-700">{t.error}</p>}
      {stage.stage_type === "TECHNICAL_INTERVIEW" && bp.length > 0 && (
        <Table head={["Competency", "Weight", "Questions", "Target depth", "Prepared questions"]}>
          {bp.map((b) => (
            <tr key={b.skill_id}>
              <td className="py-2 pr-3 font-medium text-gray-900">{b.name}{b.required ? "" : " (preferred)"}</td>
              <td className="pr-3">{b.share_pct}%</td>
              <td className="pr-3">{b.min_questions}–{b.max_questions}</td>
              <td className="pr-3">Layer {b.target_depth} of 5</td>
              <td className="pr-3">{(byComp[b.name] ?? []).length}</td>
            </tr>
          ))}
        </Table>
      )}
      {stage.stage_type === "TECHNICAL_INTERVIEW" && <p className="text-gray-500">Depth layers: core concept → how and why → applied scenario → edge case → trade-off. The next layer follows the quality of the previous answer.</p>}
      {stage.stage_type === "HR_INTERVIEW" && (
        <div className="flex flex-wrap gap-1.5">
          {(cfg.categories ?? []).map((c: string) => (
            <Badge key={c} tone="gray">{`${HR_CATEGORY_LABEL[c] ?? c}: ${(t.questions ?? []).filter((q: any) => q.category === c).length}`}</Badge>
          ))}
        </div>
      )}
      <p className="text-gray-500">{(t.questions ?? []).length} questions prepared</p>
      {!published && (
        <Button variant="secondary" size="sm" onClick={() => rebuild.mutate()} disabled={rebuild.isPending || t.status === "PREPARING"}>
          Rebuild question pool
        </Button>
      )}
      <ErrorBox error={rebuild.error} />
    </div>
  );
}

export default function HiringProcessPanel({ job }: { job: any }) {
  const qc = useQueryClient();
  const pipe = useQuery({
    queryKey: ["pipeline-config", job.id],
    queryFn: () => api.get(`/hiring-pipeline/jobs/${job.id}`).then((r) => r.data),
  });
  const gen = useQuery({
    queryKey: ["stage-generation", job.id],
    queryFn: () => api.get(`/hiring-pipeline/jobs/${job.id}/generation`).then((r) => r.data as any[]),
    refetchInterval: (q) => ((q.state.data ?? []).some((g: any) => ["PENDING", "RUNNING"].includes(g.status)) ? 3000 : false),
  });
  const [draft, setDraft] = useState<StageView[]>([]);
  const [dirty, setDirty] = useState(false);
  const [selected, setSelected] = useState<string>("TECHNICAL_ASSESSMENT");

  useEffect(() => {
    if (pipe.data && !dirty) setDraft(pipe.data.stages);
  }, [pipe.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const busy = (gen.data ?? []).filter((g) => ["PENDING", "RUNNING"].includes(g.status)).map((g) => g.stage_type);
  const busyKey = busy.join(",");
  useEffect(() => {
    if (busy.length === 0) {
      qc.invalidateQueries({ queryKey: ["pipeline-config", job.id] });
      qc.invalidateQueries({ queryKey: ["assessment-detail"] });
      qc.invalidateQueries({ queryKey: ["interview-template", job.id] });
      qc.invalidateQueries({ queryKey: ["job", job.id] });
    }
  }, [busyKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const skills = job.skills ?? [];
  const published = !!pipe.data?.published;
  const save = useMutation({
    mutationFn: () => api.put(`/hiring-pipeline/jobs/${job.id}`, { stages: draft.map(toPayload) }).then((r) => r.data),
    onSuccess: () => {
      setDirty(false);
      qc.invalidateQueries({ queryKey: ["pipeline-config", job.id] });
    },
  });
  const generate = useMutation({
    mutationFn: (type: string) => api.post(`/hiring-pipeline/jobs/${job.id}/stages/${type}/generate`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["stage-generation", job.id] }),
  });
  const publish = useMutation({
    mutationFn: () => api.post(`/hiring-pipeline/jobs/${job.id}/publish`),
    onSuccess: () => {
      ["job", "pipeline-config", "jobs"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
    },
  });

  if (pipe.isLoading) return <Loading />;
  if (pipe.error) return <ErrorBox error={pipe.error} onRetry={pipe.refetch} />;

  const change = (next: StageView[]) => {
    setDraft(next);
    setDirty(true);
  };
  const patch = (type: string, p: Partial<StageView>) => change(draft.map((s) => (s.stage_type === type ? { ...s, ...p } : s)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= draft.length || draft[j].group !== draft[i].group) return;
    const next = [...draft];
    [next[i], next[j]] = [next[j], next[i]];
    change(next);
  };
  const sel = draft.find((s) => s.stage_type === selected) ?? draft[0];
  const requirementsReady = ["REQUIREMENTS_CONFIRMED", "ASSESSMENT_READY", "PUBLISHED"].includes(job.status);
  const generating = (t: string) => busy.includes(t);
  const genRow = (t: string) => (gen.data ?? []).find((g) => g.stage_type === t);
  const enabledCount = draft.filter((s) => s.enabled).length;
  const orderNo = (s: StageView) => (s.enabled ? draft.filter((x) => x.enabled).indexOf(s) + 1 : null);

  return (
    <div className="space-y-5">
      <Card
        title="Hiring process"
        description="Choose the stages candidates go through for this role, in order. Turn off any stage you do not need."
        actions={published ? <Badge>PUBLISHED</Badge> : null}
      >
        <ol className="space-y-2" data-testid="stage-list">
          {draft.map((s, i) => {
            const state = displayState(s, dirty, published, generating(s.stage_type));
            const active = sel?.stage_type === s.stage_type;
            return (
              <li
                key={s.stage_type}
                data-testid={`stage-row-${s.stage_type}`}
                className={`flex flex-wrap items-center gap-3 rounded-lg border p-3 ${active ? "border-blue-500 bg-blue-50/40" : "border-gray-200 bg-white"} ${s.enabled ? "" : "opacity-70"}`}
              >
                <span aria-hidden="true" className={`flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold ${s.enabled ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500"}`}>
                  {orderNo(s) ?? "–"}
                </span>
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold text-gray-900">{s.label}</p>
                  <p className="text-xs text-gray-500">{STAGE_BLURB[s.stage_type]}</p>
                  {s.enabled && <p className="text-xs text-gray-500 mt-0.5">{displayDetail(s, dirty)}</p>}
                </div>
                <Badge>{state}</Badge>
                <label className="flex items-center gap-1.5 text-xs text-gray-700">
                  <input
                    type="checkbox"
                    checked={s.enabled}
                    disabled={published}
                    onChange={(e) => patch(s.stage_type, { enabled: e.target.checked })}
                    aria-label={`Include ${s.label}`}
                    data-testid={`stage-toggle-${s.stage_type}`}
                  />
                  Enabled
                </label>
                <div className="flex items-center gap-1">
                  <button type="button" className="rounded border border-gray-300 px-1.5 py-0.5 text-xs disabled:opacity-40" disabled={published || i === 0 || draft[i - 1].group !== s.group}
                    onClick={() => move(i, -1)} aria-label={`Move ${s.label} up`} data-testid={`stage-up-${s.stage_type}`}>↑</button>
                  <button type="button" className="rounded border border-gray-300 px-1.5 py-0.5 text-xs disabled:opacity-40" disabled={published || i === draft.length - 1 || draft[i + 1].group !== s.group}
                    onClick={() => move(i, 1)} aria-label={`Move ${s.label} down`} data-testid={`stage-down-${s.stage_type}`}>↓</button>
                </div>
                <Button variant={active ? "primary" : "secondary"} size="sm" onClick={() => setSelected(s.stage_type)} data-testid={`stage-configure-${s.stage_type}`}>
                  {active ? "Selected" : s.enabled ? "Configure" : "View"}
                </Button>
              </li>
            );
          })}
        </ol>
        <p className="text-xs text-gray-500">Assessments always come before interviews. You can reorder stages inside each group.</p>
        {dirty && !published && (
          <div className="flex items-center gap-3 rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900" role="status">
            <span className="flex-1">You have unsaved changes to the hiring process.</span>
            <Button size="sm" onClick={() => save.mutate()} disabled={save.isPending || enabledCount === 0} data-testid="stage-save">
              {save.isPending ? "Saving…" : "Save hiring process"}
            </Button>
            <Button size="sm" variant="ghost" onClick={() => { setDirty(false); setDraft(pipe.data.stages); }}>Discard</Button>
          </div>
        )}
        <ErrorBox error={save.error} />
      </Card>

      {sel && (
        <Card
          title={`${sel.label}${sel.enabled ? "" : " (not included)"}`}
          description={sel.enabled ? "Settings and content for this stage." : "Turn this stage on above to configure it."}
          actions={sel.enabled ? <Badge>{displayState(sel, dirty, published, generating(sel.stage_type))}</Badge> : null}
        >
          {!sel.enabled ? (
            <Empty>This stage is not part of the hiring process for this role. Candidates will not see it.</Empty>
          ) : (
            <div className="space-y-5">
              <StageSettings stage={sel} skills={skills} disabled={published} update={(p) => patch(sel.stage_type, p)} />
              {sel.stage_type !== "HR_INTERVIEW" ? (
                <QualificationSettings
                  key={`${sel.stage_type}-${published}-${sel.pass_threshold}-${sel.auto_qualify}`}
                  job={job}
                  stage={sel}
                  published={published}
                  nextLabel={(() => {
                    const on = draft.filter((x) => x.enabled);
                    const nx = on[on.findIndex((x) => x.stage_type === sel.stage_type) + 1];
                    return nx ? nx.label : "Final review by your team";
                  })()}
                  update={(p) => patch(sel.stage_type, p)}
                />
              ) : (
                <p className="rounded-lg border border-gray-200 bg-gray-50/60 p-3 text-xs text-gray-600">
                  The HR interview has no score and no pass threshold: a person decides after reading the notes.
                </p>
              )}
              {!published && (
                <div className="space-y-2 border-t border-gray-100 pt-4">
                  {!requirementsReady && <p className="text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded p-2">Confirm the job requirements (Requirements tab) before preparing this stage.</p>}
                  {dirty && <p className="text-xs text-amber-800">Save your changes before preparing this stage.</p>}
                  {generating(sel.stage_type) && (
                    <div className="flex items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800" role="status">
                      <svg className="animate-spin h-4 w-4 shrink-0" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z" /></svg>
                      Preparing {sel.label}… this can take a minute or two.
                    </div>
                  )}
                  {genRow(sel.stage_type)?.status === "FAILED" && !generating(sel.stage_type) && (
                    <ErrorBox error={{ message: `${sel.label} could not be prepared: ${genRow(sel.stage_type).error ?? "please try again"}` }} onRetry={() => generate.mutate(sel.stage_type)} />
                  )}
                  <div className="flex flex-wrap items-center gap-2">
                    <Button
                      onClick={() => generate.mutate(sel.stage_type)}
                      disabled={!requirementsReady || dirty || generate.isPending || generating(sel.stage_type)}
                      data-testid="stage-generate"
                    >
                      {isInterview(sel.stage_type) ? (sel.readiness.state === "READY" ? "Prepare again" : "Prepare interview") : sel.readiness.questions ? "Generate again" : "Generate questions"}
                    </Button>
                    {DOMAIN_OF[sel.stage_type] && (
                      <Link className="text-xs font-medium text-blue-700 hover:underline" to={`/company/jobs/${job.id}/question-bank?domain=${DOMAIN_OF[sel.stage_type]}`} data-testid="stage-bank-link">
                        Use your private question bank for this stage →
                      </Link>
                    )}
                  </div>
                  <ErrorBox error={generate.error} />
                </div>
              )}
              <div className="border-t border-gray-100 pt-4">
                {isInterview(sel.stage_type) ? <InterviewContent job={job} stage={sel} published={published} /> : <AssessmentContent stage={sel} />}
              </div>
            </div>
          )}
        </Card>
      )}

      <Card title="Publish" description="Publishing freezes every enabled stage: candidates who start are always graded on the version they began.">
        {published ? (
          <p className="text-sm text-emerald-800" data-testid="pipeline-published">
            ✓ This hiring process is published{job.institution_approval === "PENDING" ? " and waiting for the campus placement officer's approval" : ""}. Stages and question content are frozen.
          </p>
        ) : (
          <>
            {(pipe.data?.issues ?? []).length > 0 ? (
              <ul className="space-y-1.5 text-sm" data-testid="publish-issues">
                {pipe.data.issues.map((i: any, k: number) => (
                  <li key={k} className="flex gap-2 text-amber-800"><span aria-hidden="true">•</span>{i.message}</li>
                ))}
              </ul>
            ) : (
              <p className="text-sm text-emerald-800">✓ Every enabled stage is ready to publish.</p>
            )}
            <div className="pt-1">
              <Button
                onClick={() => publish.mutate()}
                disabled={!pipe.data?.can_publish || dirty || publish.isPending || !requirementsReady}
                data-testid="stage-publish"
              >
                {publish.isPending ? "Publishing…" : "Publish hiring process"}
              </Button>
              {dirty && <span className="ml-3 text-xs text-amber-800">Save your changes first.</span>}
            </div>
            <ErrorBox error={publish.error} />
          </>
        )}
      </Card>
    </div>
  );
}
