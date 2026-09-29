import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Table,
  Tabs,
  humanize,
  inputCls,
  pct,
  questionTypeLabel,
} from "../../components/ui";
import { JobFacts } from "../../components/JobSummary";
import { SkillPicker } from "../../components/SkillPicker";
import { PostingFormFields } from "../../components/PostingFormFields";
import { fromJob, problems, toPayload, type PostingForm } from "../../lib/posting";

type Req = {
  id?: string;
  skill_id: string | null;
  raw_skill_name: string;
  canonical_name?: string | null;
  requirement_type: "required" | "preferred";
  minimum_level: number;
  importance: number;
  extraction_confidence?: number;
  evidence_text?: string | null;
  delete?: boolean;
};

const EDITABLE = ["DRAFT", "SKILLS_EXTRACTED", "REQUIREMENTS_CONFIRMED"];

function RequirementsEditor({ job }: { job: any }) {
  const qc = useQueryClient();
  const [rows, setRows] = useState<Req[]>([]);
  useEffect(() => {
    setRows(job.skills.map((s: Req) => ({ ...s })));
  }, [job.skills]);
  const editable = EDITABLE.includes(job.status);
  const confirm = useMutation({
    mutationFn: () =>
      api.put(`/jobs/${job.id}/requirements/confirm`, {
        skills: rows.map((r) => ({
          id: r.id,
          skill_id: r.skill_id,
          raw_skill_name: r.raw_skill_name,
          requirement_type: r.requirement_type,
          minimum_level: Number(r.minimum_level),
          importance: Number(r.importance),
          delete: !!r.delete,
        })),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", job.id] }),
  });
  const set = (i: number, patch: Partial<Req>) =>
    setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const live = rows.filter((r) => !r.delete);
  const unmappedCount = live.filter((r) => !r.skill_id).length;

  return (
    <Card
      title="Skill Requirements"
      description="Review and configure required and preferred competencies for this role."
      actions={
        job.status === "REQUIREMENTS_CONFIRMED" ? (
          <Badge tone="green">Requirements confirmed</Badge>
        ) : unmappedCount > 0 ? (
          <Badge tone="amber">{`${unmappedCount} unmapped`}</Badge>
        ) : null
      }
    >
      <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-800">
        AI-extracted competencies are suggestions until confirmed. Each requirement must map to a
        canonical skill before generating the assessment.
      </div>
      {live.length === 0 && <Empty>No requirements added yet.</Empty>}
      {live.length > 0 && (
        <Table head={["Skill", "Requirement Type", "Min Level", "Importance", "Confidence", "Actions"]}>
          {rows.map((r, i) =>
            r.delete ? null : (
              <tr key={r.id ?? `new-${i}`} className="hover:bg-gray-50/50">
                <td className="py-2.5 pr-3">
                  <div className="font-medium text-gray-900">{r.canonical_name ?? r.raw_skill_name}</div>
                  {!r.skill_id && (
                    <div className="text-xs text-red-600 mt-1 flex flex-col gap-1">
                      <span>Not mapped: “{r.raw_skill_name}”</span>
                      <SkillPicker onPick={(s) => set(i, { skill_id: s.id, canonical_name: s.canonical_name })} />
                    </div>
                  )}
                  {r.evidence_text && <div className="text-xs text-gray-500 italic mt-0.5">“{r.evidence_text}”</div>}
                </td>
                <td className="pr-3">
                  <select
                    disabled={!editable}
                    className={`${inputCls} min-w-[7.5rem]`}
                    value={r.requirement_type}
                    onChange={(e) => set(i, { requirement_type: e.target.value as Req["requirement_type"] })}
                  >
                    <option value="required">Required</option>
                    <option value="preferred">Preferred</option>
                  </select>
                </td>
                <td className="pr-3 w-32">
                  <div className="flex items-center gap-1.5">
                    <input
                      disabled={!editable}
                      className={`${inputCls} w-20`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={r.minimum_level}
                      onChange={(e) => set(i, { minimum_level: Number(e.target.value) })}
                    />
                    <span className="text-xs text-gray-500 tabular-nums font-mono">{pct(r.minimum_level)}</span>
                  </div>
                </td>
                <td className="pr-3 w-32">
                  <div className="flex items-center gap-1.5">
                    <input
                      disabled={!editable}
                      className={`${inputCls} w-20`}
                      type="number"
                      min={0}
                      max={1}
                      step={0.05}
                      value={r.importance}
                      onChange={(e) => set(i, { importance: Number(e.target.value) })}
                    />
                    <span className="text-xs text-gray-500 tabular-nums font-mono">{pct(r.importance)}</span>
                  </div>
                </td>
                <td className="pr-3 text-xs text-gray-500">
                  {r.evidence_text ? pct(r.extraction_confidence) : "Direct addition"}
                </td>
                <td>
                  {editable && (
                    <Button variant="danger" size="sm" onClick={() => set(i, { delete: true })}>
                      Remove
                    </Button>
                  )}
                </td>
              </tr>
            )
          )}
        </Table>
      )}
      {editable && (
        <div className="flex flex-col sm:flex-row items-stretch sm:items-end gap-3 pt-3 border-t border-gray-100">
          <div className="w-full sm:w-80">
            <p className="text-xs font-medium text-gray-700 mb-1">Add another competency</p>
            <SkillPicker
              onPick={(s) =>
                setRows((rs) => [
                  ...rs,
                  {
                    skill_id: s.id,
                    raw_skill_name: s.canonical_name,
                    canonical_name: s.canonical_name,
                    requirement_type: "required",
                    minimum_level: 0.5,
                    importance: 0.5,
                  },
                ])
              }
            />
          </div>
          <Button onClick={() => confirm.mutate()} disabled={confirm.isPending || live.length === 0}>
            {confirm.isPending ? "Confirming…" : "Confirm requirements"}
          </Button>
        </div>
      )}
      <ErrorBox error={confirm.error} />
    </Card>
  );
}

function DeliveryOptions({ assessment, estimated }: { assessment: any; estimated?: number }) {
  const qc = useQueryClient();
  const cfg = assessment.config ?? {};
  const [minutes, setMinutes] = useState<string>(
    String(cfg.duration_minutes ?? estimated ?? assessment.total_duration_minutes ?? 60)
  );
  const [rq, setRq] = useState<boolean>(cfg.randomize_questions ?? true);
  const [ro, setRo] = useState<boolean>(cfg.randomize_options ?? true);
  const save = useMutation({
    mutationFn: () =>
      api.put(`/assessments/${assessment.id}/config`, {
        duration_minutes: Number(minutes),
        randomize_questions: rq,
        randomize_options: ro,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assessment-by-job"] }),
  });
  return (
    <div className="border border-gray-200 bg-gray-50/50 rounded-lg p-3.5 text-sm space-y-2.5" data-testid="delivery-options">
      <div>
        <p className="text-xs font-semibold text-gray-800">Assessment Delivery Options</p>
        <p className="text-xs text-gray-500">Settings will be locked and frozen when published.</p>
      </div>
      <div className="flex flex-wrap items-center gap-4 text-xs">
        <label className="flex items-center gap-2">
          <span className="font-medium text-gray-700">Time limit (minutes)</span>
          <input
            className={`${inputCls} w-20`}
            value={minutes}
            onChange={(e) => setMinutes(e.target.value)}
          />
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer text-gray-700">
          <input type="checkbox" className="rounded text-blue-600" checked={rq} onChange={(e) => setRq(e.target.checked)} />
          <span>Shuffle question order</span>
        </label>
        <label className="flex items-center gap-1.5 cursor-pointer text-gray-700">
          <input type="checkbox" className="rounded text-blue-600" checked={ro} onChange={(e) => setRo(e.target.checked)} />
          <span>Shuffle answer options</span>
        </label>
        <Button variant="secondary" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
          Save options
        </Button>
        {save.isSuccess && <span className="text-xs font-medium text-emerald-700">✓ Saved</span>}
      </div>
      <ErrorBox error={save.error} />
    </div>
  );
}

function AssessmentPanel({ job, processing }: { job: any; processing: any }) {
  const qc = useQueryClient();
  const { data: assessment } = useQuery({
    queryKey: ["assessment-by-job", job.id],
    queryFn: () => api.get(`/assessments/by-job/${job.id}`).then((r) => r.data),
  });
  const { data: detail, error: detailError, refetch } = useQuery({
    queryKey: ["assessment-detail", assessment?.id],
    queryFn: () => api.get(`/assessments/${assessment.id}`).then((r) => r.data),
    enabled: !!assessment?.id,
  });
  const gen = processing?.assessment;
  const [target, setTarget] = useState("12");

  const generate = useMutation({
    mutationFn: () =>
      api.post(`/assessments/jobs/${job.id}/generate`, {
        title: `${job.title} Assessment`,
        total_questions: Number(target) || null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["processing", job.id] }),
  });
  const publish = useMutation({
    mutationFn: () => api.post(`/assessments/${assessment.id}/publish`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["job", job.id] });
      qc.invalidateQueries({ queryKey: ["assessment-by-job", job.id] });
    },
  });
  useEffect(() => {
    if (gen?.status === "COMPLETED") {
      qc.invalidateQueries({ queryKey: ["assessment-by-job", job.id] });
      refetch();
    }
  }, [gen?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const canGenerate = ["REQUIREMENTS_CONFIRMED", "ASSESSMENT_READY"].includes(job.status) && assessment?.status !== "PUBLISHED";
  const questions = (detail?.sections ?? []).flatMap((s: any) =>
    s.questions.map((q: any) => ({ ...q.question, section: s.title }))
  );
  const plan = detail?.plan;

  return (
    <Card
      title="Technical Assessment"
      description="Configure, generate, and review test questions and proctored delivery rules."
      actions={assessment ? <Badge>{assessment.status}</Badge> : null}
    >
      {!canGenerate && !assessment && (
        <Empty>Confirm the skill requirements above to generate an assessment.</Empty>
      )}

      {job.status !== "DRAFT" && job.status !== "SKILLS_EXTRACTED" && (
        <div className="flex items-center justify-between bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs">
          <div className="text-blue-900">
            <strong>Company-Private Question Bank:</strong> Questions from your bank are prioritized before AI fills gaps.
          </div>
          <Link
            className="font-medium text-blue-700 hover:text-blue-900 underline shrink-0"
            to={`/company/jobs/${job.id}/question-bank`}
            data-testid="private-bank-link"
          >
            Manage Question Bank →
          </Link>
        </div>
      )}

      {gen && (gen.status === "PENDING" || gen.status === "RUNNING") && (
        <div className="flex items-center gap-3 p-3 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
          <svg className="animate-spin h-4 w-4 text-amber-600 shrink-0" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.37 0 0 5.37 0 12h4z" />
          </svg>
          <span>Generating assessment blueprint and questions… this may take 1–2 minutes.</span>
        </div>
      )}

      {gen?.status === "FAILED" && (
        <ErrorBox
          error={{ message: `Assessment generation failed: ${gen.error}` }}
          onRetry={() => generate.mutate()}
        />
      )}

      {canGenerate && (
        <div className="flex items-center gap-3 text-xs text-gray-700">
          <label className="flex items-center gap-1.5">
            <span className="font-medium">Target number of questions:</span>
            <input
              className={`${inputCls} w-20`}
              value={target}
              onChange={(e) => setTarget(e.target.value)}
              data-testid="target-questions"
            />
          </label>
          <span className="text-gray-400">(Recommended: 6–30 questions)</span>
        </div>
      )}

      {assessment && assessment.status !== "PUBLISHED" && (
        <DeliveryOptions assessment={assessment} estimated={detail?.plan?.estimated_duration_minutes} />
      )}

      <div className="flex flex-wrap gap-2 pt-2">
        {canGenerate && (
          <Button
            onClick={() => generate.mutate()}
            disabled={generate.isPending || gen?.status === "RUNNING" || gen?.status === "PENDING"}
          >
            {assessment ? "Regenerate assessment" : "Generate assessment"}
          </Button>
        )}
        {assessment && assessment.status !== "PUBLISHED" && questions.length > 0 && (
          <Button
            variant="secondary"
            onClick={() => publish.mutate()}
            disabled={publish.isPending}
          >
            {publish.isPending ? "Publishing…" : "Publish assessment"}
          </Button>
        )}
      </div>

      <ErrorBox error={generate.error || publish.error || detailError} />

      {plan?.coverage && (
        <div className="border border-gray-200 rounded-lg p-4 bg-white space-y-2 text-xs" data-testid="coverage">
          <div className="flex items-center justify-between">
            <span className="font-semibold text-gray-800 text-sm">Question Coverage Blueprint</span>
            <Badge tone={plan.coverage.covered_slots === plan.coverage.required_slots ? "green" : "amber"}>
              {`${plan.coverage.covered_slots} / ${plan.coverage.required_slots} slots covered (${plan.coverage.coverage_percentage}%)`}
            </Badge>
          </div>
          <div className="flex flex-wrap gap-x-4 gap-y-1 text-gray-600">
            <span>Duration: ~{plan.estimated_duration_minutes} min</span>
            <span>Total Questions: {plan.total_questions}</span>
            <span>Covered Competencies: {plan.covered_skills.length}</span>
            {plan.missing_coverage.length > 0 && (
              <span className="text-red-600 font-medium">Missing: {plan.missing_coverage.length}</span>
            )}
          </div>
          {plan.coverage.uncovered_slots.length > 0 && (
            <div className="mt-2 p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-900">
              <p className="font-medium">
                {plan.coverage.uncovered_slots.reduce((n: number, u: any) => n + u.missing, 0)} slot(s) need additional questions:
              </p>
              <ul className="list-disc ml-4 mt-1 space-y-0.5">
                {plan.coverage.uncovered_slots.map((u: any) => (
                  <li key={u.skill + u.question_type}>
                    {u.skill} ({questionTypeLabel(u.question_type)}) × {u.missing}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {questions.length > 0 && (
        <div className="space-y-2 pt-2">
          <h3 className="text-xs font-semibold text-gray-700">Question Pool ({questions.length})</h3>
          <Table head={["Skill", "Type", "Source", "Status", "Question"]}>
            {questions.map((q: any) => (
              <tr key={q.id} className="align-top hover:bg-gray-50/50">
                <td className="py-2.5 pr-3 font-medium text-gray-900 whitespace-nowrap">{q.section}</td>
                <td className="pr-3">
                  <Badge tone="gray">{questionTypeLabel(q.question_type)}</Badge>
                </td>
                <td className="pr-3 text-xs text-gray-600">{humanize(q.source_type)}</td>
                <td className="pr-3">
                  <Badge>{q.status}</Badge>
                </td>
                <td className="pr-3 text-xs text-gray-700 leading-relaxed max-w-md">{q.question_text}</td>
              </tr>
            ))}
          </Table>
        </div>
      )}
    </Card>
  );
}

function Candidates({ job }: { job: any }) {
  const qc = useQueryClient();
  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["job-applications", job.id],
    queryFn: () => api.get(`/applications/job/${job.id}`).then((r) => r.data),
  });
  const matching = useQuery({
    queryKey: ["matching-status", job.id],
    queryFn: () => api.get(`/jobs/${job.id}/processing`).then((r) => r.data?.matching),
    refetchInterval: (q) => (["PENDING", "RUNNING"].includes((q.state.data as any)?.status) ? 2000 : false),
  });
  const running = ["PENDING", "RUNNING"].includes(matching.data?.status);
  useEffect(() => {
    if (!running) qc.invalidateQueries({ queryKey: ["job-applications", job.id] });
  }, [running]); // eslint-disable-line
  const recompute = useMutation({
    mutationFn: () => api.post(`/matching/jobs/${job.id}/recompute`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["matching-status", job.id] }),
  });
  return (
    <Card
      title="Candidate Applications"
      description="Review candidates who have applied for this position."
      actions={
        <Button
          variant="secondary"
          size="sm"
          onClick={() => recompute.mutate()}
          disabled={recompute.isPending || running}
        >
          {running ? "Scoring candidates…" : "Recompute match scores"}
        </Button>
      }
    >
      {isLoading && <Loading />}
      <ErrorBox error={error || recompute.error} onRetry={refetch} />
      {data?.length === 0 && <Empty>No applications received for this position yet.</Empty>}
      {data?.length > 0 && (
        <Table head={["Candidate Name", "Application Status", "Skill Match", "Applied Date", "Action"]}>
          {data.map((a: any) => (
            <tr key={a.id} className="hover:bg-gray-50/50">
              <td className="py-2.5 pr-3 font-medium text-gray-900">{a.student_name}</td>
              <td className="pr-3">
                <Badge>{a.status}</Badge>
              </td>
              <td className="pr-3">
                {a.match_score == null ? (
                  <span className="text-xs text-gray-400">Pending</span>
                ) : (
                  <span className="font-semibold text-gray-900">{pct(a.match_score, 1)}</span>
                )}
              </td>
              <td className="pr-3 text-xs text-gray-500">
                {a.applied_at ? new Date(a.applied_at).toLocaleDateString() : "—"}
              </td>
              <td>
                <Link
                  className="inline-flex items-center text-xs font-semibold text-blue-700 hover:text-blue-900"
                  to={`/company/applications/${a.id}`}
                >
                  Review Candidate →
                </Link>
              </td>
            </tr>
          ))}
        </Table>
      )}
    </Card>
  );
}

function InterviewPlanCard({ job }: { job: any }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const plan = useQuery({
    queryKey: ["interview-template", job.id],
    queryFn: () => api.get(`/interviews/templates/by-job/${job.id}`).then((r) => r.data),
    refetchInterval: (q) => (q.state.data?.status === "PREPARING" ? 3000 : false),
  });
  const rebuild = useMutation({
    mutationFn: () => api.post(`/interviews/templates/by-job/${job.id}/rebuild`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-template", job.id] }),
  });
  const t = plan.data;
  const count = (skill: string, d: string) =>
    (t?.questions ?? []).filter((q: any) => q.skill === skill && q.difficulty === d).length;

  return (
    <Card
      title="AI Interview Plan"
      description="Standardized conversational interview blueprint grounded in role requirements."
      actions={t ? <Badge>{t.status}</Badge> : null}
    >
      {!t && <Empty>Interview plan is prepared automatically when you publish the assessment.</Empty>}
      {t && (
        <div className="space-y-3 text-sm" data-testid="interview-plan">
          <p className="text-xs text-gray-600">
            Candidates are interviewed consistently against the same rubric. Questions
            are selected deterministically from the pool (prioritizing company question bank, then verified AI templates).
            Planned length: {t.config.min_questions}–{t.config.max_questions} questions (~{t.config.recommended_minutes} min).
          </p>
          {t.status === "PREPARING" && <p className="text-amber-700 text-xs">Preparing question pool…</p>}
          {t.error && <p className="text-red-600 text-xs">{t.error}</p>}
          <Table head={["Competency", "Importance", "Required", "Easy", "Medium", "Hard"]}>
            {t.config.competencies.map((c: any) => (
              <tr key={c.skill_id} className="hover:bg-gray-50/50">
                <td className="py-1.5 pr-3 font-medium text-gray-900">{c.name}</td>
                <td className="pr-3 text-xs">{pct(c.importance)}</td>
                <td className="pr-3 text-xs">{c.required ? "Yes" : "Optional"}</td>
                {["easy", "medium", "hard"].map((d) => (
                  <td key={d} className="pr-3 text-xs text-gray-600">
                    {count(c.name, d) || "—"}
                  </td>
                ))}
              </tr>
            ))}
          </Table>
          <div className="flex gap-2 pt-1">
            <Button variant="secondary" size="sm" onClick={() => setOpen((v) => !v)}>
              {open ? "Hide questions" : `Review question pool (${t.questions.length})`}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => rebuild.mutate()}
              disabled={rebuild.isPending || t.status === "PREPARING"}
            >
              Rebuild pool
            </Button>
          </div>
          {open && (
            <ul className="text-xs space-y-1.5 bg-gray-50 p-3 rounded-lg border border-gray-100 max-h-60 overflow-y-auto">
              {t.questions.map((q: any) => (
                <li key={q.id} className="flex items-start gap-2">
                  <Badge tone="gray">{`${q.skill} · ${q.difficulty}`}</Badge>
                  <span className="text-gray-800">{q.question_text}</span>
                </li>
              ))}
            </ul>
          )}
          <ErrorBox error={rebuild.error} />
        </div>
      )}
    </Card>
  );
}

function PostingCard({ job }: { job: any }) {
  const qc = useQueryClient();
  const published = job.status === "PUBLISHED";
  const [edit, setEdit] = useState(false);
  const [f, setF] = useState<PostingForm>(() => fromJob(job));
  const save = useMutation({
    mutationFn: () => api.put(`/jobs/${job.id}/posting`, toPayload(f)),
    onSuccess: () => {
      setEdit(false);
      qc.invalidateQueries({ queryKey: ["job", job.id] });
      qc.invalidateQueries({ queryKey: ["jobs-org"] });
    },
  });
  const missing = [
    !job.employment_type && "employment type",
    !job.work_mode && "work mode",
    (job.work_mode === "ONSITE" || job.work_mode === "HYBRID") &&
      !(job.location_city && job.location_country) &&
      "city and country",
  ].filter(Boolean);

  return (
    <Card
      title="Role Overview & Compensation"
      actions={
        !edit ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setF(fromJob(job));
              setEdit(true);
            }}
          >
            {published ? "Extend deadline / openings" : "Edit Details"}
          </Button>
        ) : null
      }
    >
      {!edit ? (
        <div className="space-y-2" data-testid="posting-summary">
          <JobFacts job={job} />
          {missing.length > 0 && (
            <p className="text-xs text-amber-700 bg-amber-50 p-2 rounded border border-amber-200" data-testid="posting-missing">
              Please specify {missing.join(", ")} before publishing.
            </p>
          )}
          {!job.display?.headline && !job.display?.compensation && (
            <p className="text-xs text-gray-500">No posting details specified yet.</p>
          )}
        </div>
      ) : (
        <div className="space-y-3">
          {published && (
            <p className="text-xs text-gray-500">
              This job is published: only application deadline and openings can be updated.
            </p>
          )}
          <PostingFormFields f={f} set={(p) => setF((x) => ({ ...x, ...p }))} lockedExceptDeadline={published} />
          <div className="flex gap-2">
            <Button onClick={() => save.mutate()} disabled={save.isPending || problems(f).length > 0}>
              {save.isPending ? "Saving…" : "Save posting details"}
            </Button>
            <Button variant="secondary" onClick={() => setEdit(false)}>
              Cancel
            </Button>
          </div>
          <ErrorBox error={save.error} />
        </div>
      )}
    </Card>
  );
}

const APPROVAL_LABEL: Record<string, string> = {
  NOT_REQUIRED: "Not submitted yet (will be submitted to institution when published)",
  PENDING: "Awaiting approval from the placement officer",
  APPROVED: "Approved: visible to eligible campus students",
  REJECTED: "Rejected by the placement officer",
};

function DistributionCard({ job }: { job: any }) {
  const qc = useQueryClient();
  const dir = useQuery({
    queryKey: ["institution-directory"],
    queryFn: () => api.get("/institutions/directory").then((r) => r.data),
  });
  const [type, setType] = useState<string>(job.distribution_type ?? "OPEN_MARKET");
  const [inst, setInst] = useState<string>(job.target_institution_id ?? "");
  const save = useMutation({
    mutationFn: () =>
      api.put(`/jobs/${job.id}/distribution`, {
        distribution_type: type,
        institution_id: type === "INSTITUTION" ? inst : null,
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", job.id] }),
  });
  const locked = job.institution_approval === "APPROVED";

  return (
    <Card
      title="Candidate Distribution"
      description="Select whether this role is open to all students or restricted to a partner campus."
      actions={
        job.distribution_type === "INSTITUTION" ? (
          <Badge>{job.institution_approval === "NOT_REQUIRED" ? "NOT SUBMITTED" : job.institution_approval}</Badge>
        ) : (
          <Badge>OPEN MARKET</Badge>
        )
      }
    >
      <div className="flex flex-col sm:flex-row gap-2.5 items-stretch sm:items-center text-sm">
        <select
          className={`${inputCls} sm:w-72`}
          aria-label="Distribution type"
          value={type}
          disabled={locked}
          onChange={(e) => setType(e.target.value)}
          data-testid="distribution-type"
        >
          <option value="OPEN_MARKET">Open Market (all students)</option>
          <option value="INSTITUTION">Partner Institution (campus drive)</option>
        </select>
        {type === "INSTITUTION" && (
          <select
            className={`${inputCls} sm:w-72`}
            value={inst}
            disabled={locked}
            onChange={(e) => setInst(e.target.value)}
            data-testid="distribution-institution"
          >
            <option value="">Select target campus…</option>
            {(dir.data ?? []).map((i: any) => (
              <option key={i.id} value={i.id}>
                {i.name}
              </option>
            ))}
          </select>
        )}
        <Button
          variant="secondary"
          size="sm"
          onClick={() => save.mutate()}
          disabled={locked || save.isPending || (type === "INSTITUTION" && !inst)}
        >
          Save distribution
        </Button>
      </div>
      {job.distribution_type === "INSTITUTION" && (
        <p className="text-xs text-gray-600 bg-gray-50 p-2.5 rounded border border-gray-100" data-testid="approval-state">
          <strong>{job.target_institution_name}:</strong> {APPROVAL_LABEL[job.institution_approval]}
        </p>
      )}
      <ErrorBox error={save.error} />
    </Card>
  );
}

export default function CompanyJobDetailPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const [jdText, setJdText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [activeTab, setActiveTab] = useState<"overview" | "requirements" | "assessment" | "candidates">("overview");

  const { data: job, isLoading, error, refetch } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data),
  });
  const { data: processing } = useQuery({
    queryKey: ["processing", jobId],
    queryFn: () => api.get(`/jobs/${jobId}/processing`).then((r) => r.data),
    refetchInterval: (q) => {
      const d: any = q.state.data;
      const busy = ["PENDING", "RUNNING"];
      return d && (busy.includes(d.jd?.status) || busy.includes(d.assessment?.status)) ? 3000 : false;
    },
  });
  useEffect(() => {
    if (processing?.jd?.status === "COMPLETED" || processing?.jd?.status === "FAILED") {
      qc.invalidateQueries({ queryKey: ["job", jobId] });
    }
  }, [processing?.jd?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const analyze = useMutation({
    mutationFn: async () => {
      if (file) {
        const fd = new FormData();
        fd.append("file", file);
        await api.post(`/jobs/${jobId}/jd-file`, fd);
      } else if (jdText.trim()) {
        await api.put(`/jobs/${jobId}/jd`, { description_raw: jdText });
      }
      return api.post(`/jobs/${jobId}/process`);
    },
    onSuccess: () => {
      setJdText("");
      setFile(null);
      qc.invalidateQueries({ queryKey: ["processing", jobId] });
      qc.invalidateQueries({ queryKey: ["job", jobId] });
    },
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={refetch} />;
  if (!job) return null;
  const jd = processing?.jd;
  const jdBusy = jd && ["PENDING", "RUNNING"].includes(jd.status);

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        back={{ label: "All jobs", href: "/company" }}
        title={job.title}
        description={job.organization_name}
        actions={<Badge>{job.status}</Badge>}
      />

      {/* Primary section navigation tabs */}
      <Tabs
        tabs={[
          { id: "overview", label: "Overview & Posting" },
          { id: "requirements", label: `Requirements (${job.skills?.length ?? 0})` },
          { id: "assessment", label: "Assessment & Interview" },
          { id: "candidates", label: "Candidates" },
        ]}
        current={activeTab}
        onChange={(t) => setActiveTab(t as any)}
      />

      {activeTab === "overview" && (
        <div className="space-y-5">
          {["DRAFT", "SKILLS_EXTRACTED"].includes(job.status) && (
            <Card
              title="Job Description"
              description="Paste text or upload a document to automatically extract required skills."
            >
              {job.description_raw && (
                <p className="text-xs text-gray-600 whitespace-pre-wrap max-h-40 overflow-auto border border-gray-100 rounded-lg p-3 bg-gray-50">
                  {job.description_raw}
                </p>
              )}
              <textarea
                className={inputCls}
                rows={7}
                placeholder="Paste the job description here…"
                value={jdText}
                onChange={(e) => setJdText(e.target.value)}
              />
              <div className="flex items-center gap-3 text-xs text-gray-600">
                <span>Or upload file (PDF, DOCX, TXT):</span>
                <input
                  type="file"
                  accept=".pdf,.docx,.txt"
                  onChange={(e) => setFile(e.target.files?.[0] ?? null)}
                />
              </div>
              <Button
                onClick={() => analyze.mutate()}
                disabled={analyze.isPending || jdBusy || (!jdText.trim() && !file && !job.description_raw)}
              >
                {jdBusy ? "Analyzing requirements…" : job.status === "SKILLS_EXTRACTED" ? "Re-analyze JD" : "Extract Requirements"}
              </Button>
              {jdBusy && (
                <p className="text-xs text-amber-700">Analyzing job description competencies…</p>
              )}
              {jd?.status === "FAILED" && (
                <ErrorBox
                  error={{ message: `Job description processing failed: ${jd.error}` }}
                  onRetry={() => analyze.mutate()}
                />
              )}
              <ErrorBox error={analyze.error} />
            </Card>
          )}

          <PostingCard key={job.updated_at ?? job.id + job.status} job={job} />
          <DistributionCard job={job} />
        </div>
      )}

      {activeTab === "requirements" && (
        <div className="space-y-5">
          <RequirementsEditor job={job} />
        </div>
      )}

      {activeTab === "assessment" && (
        <div className="space-y-5">
          <AssessmentPanel job={job} processing={processing} />
          <InterviewPlanCard job={job} />
        </div>
      )}

      {activeTab === "candidates" && (
        <div className="space-y-5">
          <Candidates job={job} />
        </div>
      )}
    </div>
  );
}
