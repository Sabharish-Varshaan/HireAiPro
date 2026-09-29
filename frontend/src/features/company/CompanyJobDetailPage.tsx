import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls, pct } from "../../components/ui";
import { JobFacts } from "../../components/JobSummary";
import { SkillPicker } from "../../components/SkillPicker";
import { PostingFormFields } from "../../components/PostingFormFields";
import { fromJob, problems, toPayload, type PostingForm } from "../../lib/posting";

type Req = {
  id?: string; skill_id: string | null; raw_skill_name: string; canonical_name?: string | null;
  requirement_type: "required" | "preferred"; minimum_level: number; importance: number;
  extraction_confidence?: number; evidence_text?: string | null; delete?: boolean;
};

const EDITABLE = ["DRAFT", "SKILLS_EXTRACTED", "REQUIREMENTS_CONFIRMED"];

function RequirementsEditor({ job }: { job: any }) {
  const qc = useQueryClient();
  const [rows, setRows] = useState<Req[]>([]);
  useEffect(() => { setRows(job.skills.map((s: Req) => ({ ...s }))); }, [job.skills]);
  const editable = EDITABLE.includes(job.status);
  const confirm = useMutation({
    mutationFn: () => api.put(`/jobs/${job.id}/requirements/confirm`, {
      skills: rows.map((r) => ({ id: r.id, skill_id: r.skill_id, raw_skill_name: r.raw_skill_name, requirement_type: r.requirement_type,
        minimum_level: Number(r.minimum_level), importance: Number(r.importance), delete: !!r.delete })),
    }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", job.id] }),
  });
  const set = (i: number, patch: Partial<Req>) => setRows((rs) => rs.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  const live = rows.filter((r) => !r.delete);

  return (
    <Card title="Requirements" actions={job.status === "REQUIREMENTS_CONFIRMED" ? <Badge>REQUIREMENTS_CONFIRMED</Badge> : null}>
      <p className="text-xs text-gray-500">
        AI suggestions are not used until you confirm them. Every requirement must map to a canonical skill; unmapped ones must be mapped or removed.
      </p>
      {live.length === 0 && <Empty>No requirements yet.</Empty>}
      {live.length > 0 && (
        <Table head={["Skill", "Type", "Min level", "Importance", "AI confidence", ""]}>
          {rows.map((r, i) => r.delete ? null : (
            <tr key={r.id ?? `new-${i}`}>
              <td className="py-2 pr-3">
                <div className="font-medium">{r.canonical_name ?? r.raw_skill_name}</div>
                {!r.skill_id && <div className="text-xs text-red-600">Not mapped: “{r.raw_skill_name}” <SkillPicker onPick={(s) => set(i, { skill_id: s.id, canonical_name: s.canonical_name })} /></div>}
                {r.evidence_text && <div className="text-xs text-gray-400">“{r.evidence_text}”</div>}
              </td>
              <td className="pr-3">
                <select disabled={!editable} className={`${inputCls} min-w-[7.5rem]`} value={r.requirement_type}
                  onChange={(e) => set(i, { requirement_type: e.target.value as Req["requirement_type"] })}>
                  <option value="required">required</option>
                  <option value="preferred">preferred</option>
                </select>
              </td>
              <td className="pr-3 w-24"><input disabled={!editable} className={inputCls} type="number" min={0} max={1} step={0.05}
                value={r.minimum_level} onChange={(e) => set(i, { minimum_level: Number(e.target.value) })} /></td>
              <td className="pr-3 w-24"><input disabled={!editable} className={inputCls} type="number" min={0} max={1} step={0.05}
                value={r.importance} onChange={(e) => set(i, { importance: Number(e.target.value) })} /></td>
              <td className="pr-3 text-xs text-gray-500">{r.evidence_text ? pct(r.extraction_confidence) : "added by recruiter"}</td>
              <td>{editable && <Button variant="danger" onClick={() => set(i, { delete: true })}>Remove</Button>}</td>
            </tr>
          ))}
        </Table>
      )}
      {editable && (
        <div className="flex items-end gap-3">
          <div className="w-72">
            <p className="text-xs text-gray-500 mb-1">Add requirement</p>
            <SkillPicker onPick={(s) => setRows((rs) => [...rs, { skill_id: s.id, raw_skill_name: s.canonical_name, canonical_name: s.canonical_name,
              requirement_type: "required", minimum_level: 0.5, importance: 0.5 }])} />
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
  const [minutes, setMinutes] = useState<string>(String(cfg.duration_minutes ?? estimated ?? assessment.total_duration_minutes ?? 60));
  const [rq, setRq] = useState<boolean>(cfg.randomize_questions ?? true);
  const [ro, setRo] = useState<boolean>(cfg.randomize_options ?? true);
  const save = useMutation({
    mutationFn: () => api.put(`/assessments/${assessment.id}/config`, { duration_minutes: Number(minutes), randomize_questions: rq, randomize_options: ro }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assessment-by-job"] }),
  });
  return (
    <div className="border border-gray-200 rounded-md p-2 text-sm space-y-2" data-testid="delivery-options">
      <p className="text-xs font-medium">Delivery options (frozen when you publish)</p>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-xs">Time limit (minutes) <input className={`${inputCls} w-20 inline-block`} value={minutes} onChange={(e) => setMinutes(e.target.value)} /></label>
        <label className="text-xs"><input type="checkbox" checked={rq} onChange={(e) => setRq(e.target.checked)} /> Shuffle question order per candidate</label>
        <label className="text-xs"><input type="checkbox" checked={ro} onChange={(e) => setRo(e.target.checked)} /> Shuffle answer options per candidate</label>
        <Button variant="secondary" onClick={() => save.mutate()} disabled={save.isPending}>Save options</Button>
        {save.isSuccess && <span className="text-xs text-green-700">Saved</span>}
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
    mutationFn: () => api.post(`/assessments/jobs/${job.id}/generate`, { title: `${job.title} Assessment`, total_questions: Number(target) || null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["processing", job.id] }),
  });
  const publish = useMutation({
    mutationFn: () => api.post(`/assessments/${assessment.id}/publish`),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["job", job.id] }); qc.invalidateQueries({ queryKey: ["assessment-by-job", job.id] }); },
  });
  useEffect(() => {
    if (gen?.status === "COMPLETED") { qc.invalidateQueries({ queryKey: ["assessment-by-job", job.id] }); refetch(); }
  }, [gen?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const canGenerate = ["REQUIREMENTS_CONFIRMED", "ASSESSMENT_READY"].includes(job.status) && assessment?.status !== "PUBLISHED";
  const questions = (detail?.sections ?? []).flatMap((s: any) => s.questions.map((q: any) => ({ ...q.question, section: s.title })));
  const plan = detail?.plan;

  return (
    <Card title="Assessment" actions={assessment ? <Badge>{assessment.status}</Badge> : null}>
      {!canGenerate && !assessment && <Empty>Confirm the requirements to generate an assessment.</Empty>}
      {job.status !== "DRAFT" && job.status !== "SKILLS_EXTRACTED" && (
        <div className="flex items-center gap-2 text-xs"><Link className="underline text-gray-700" to={`/company/jobs/${job.id}/question-bank`} data-testid="private-bank-link">Private question bank</Link>
          <span className="text-gray-500">import, add or reuse your own questions before AI fills the gaps</span></div>)}
      {gen && (gen.status === "PENDING" || gen.status === "RUNNING") && (
        <p className="text-sm text-amber-700">Generating (Assessment Agent)… this can take a few minutes. Status: {gen.status}</p>
      )}
      {gen?.status === "FAILED" && <ErrorBox error={{ message: `Generation failed: ${gen.error}` }} onRetry={() => generate.mutate()} />}
      {canGenerate && (
        <label className="text-xs text-gray-600">Target number of questions <input className={`${inputCls} w-16 inline-block`} value={target} onChange={(e) => setTarget(e.target.value)} data-testid="target-questions" /> (6–30)</label>)}
      {assessment && assessment.status !== "PUBLISHED" && <DeliveryOptions assessment={assessment} estimated={detail?.plan?.estimated_duration_minutes} />}
      <div className="flex gap-2">
        {canGenerate && (
          <Button onClick={() => generate.mutate()} disabled={generate.isPending || gen?.status === "RUNNING" || gen?.status === "PENDING"}>
            {assessment ? "Regenerate assessment" : "Generate assessment"}
          </Button>
        )}
        {assessment && assessment.status !== "PUBLISHED" && questions.length > 0 && (
          <Button variant="secondary" onClick={() => publish.mutate()} disabled={publish.isPending}>Publish</Button>
        )}
      </div>
      <ErrorBox error={generate.error || publish.error || detailError} />
      {plan && (
        <div className="text-xs text-gray-600 flex flex-wrap gap-x-4 gap-y-1">
          <span>{plan.total_questions} questions</span>
          <span>~{plan.estimated_duration_minutes} min</span>
          <span>covered skills: {plan.covered_skills.length}</span>
          <span className={plan.missing_coverage.length ? "text-red-600" : ""}>missing coverage: {plan.missing_coverage.length}</span>
          {plan.sections.map((s: any) => (
            <span key={s.skill_name}>{s.skill_name}: {s.reused_company} company · {s.reused_platform} platform · {s.generated} generated ({s.grounded} grounded)</span>
          ))}
        </div>
      )}
      {plan?.coverage && (
        <div className="text-sm border border-gray-200 rounded-md p-3 space-y-1" data-testid="coverage">
          <p><b>{plan.coverage.covered_slots}/{plan.coverage.required_slots} question slots covered</b> ({plan.coverage.coverage_percentage}%) ·
            {" "}{plan.coverage.generation_attempts} generation attempts (max {plan.coverage.attempts_per_slot} per slot)
            {plan.dropped_duplicates?.length ? ` · ${plan.dropped_duplicates.length} duplicate(s) dropped` : ""}</p>
          {plan.coverage.uncovered_slots.length > 0 && (
            <div className="text-amber-800">
              <p>{plan.coverage.uncovered_slots.reduce((n: number, u: any) => n + u.missing, 0)} slot(s) could not be safely generated.
                Add a question for these in the <a className="underline" href="/company/questions">question bank</a>, then regenerate:</p>
              <ul className="list-disc ml-5">
                {plan.coverage.uncovered_slots.map((u: any) => (
                  <li key={u.skill + u.question_type}>{u.skill} · {u.question_type} × {u.missing}
                    {u.rejection_reasons.length > 0 && <span className="text-xs text-gray-600"> — rejected: {u.rejection_reasons.join(" | ").slice(0, 240)}</span>}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
      {questions.length > 0 && (
        <Table head={["Skill", "Type", "Origin", "Status", "Question", "Provenance"]}>
          {questions.map((q: any) => (
            <tr key={q.id} className="align-top">
              <td className="py-2 pr-3 whitespace-nowrap">{q.section}</td>
              <td className="pr-3"><Badge tone="gray">{q.question_type}</Badge></td>
              <td className="pr-3 text-xs">{q.source_type}{q.model_version ? ` · ${q.model_version}` : ""}</td>
              <td className="pr-3"><Badge>{q.status}</Badge></td>
              <td className="pr-3">{q.question_text}</td>
              <td className="text-xs text-gray-500">
                {(q.source_refs ?? []).length === 0 ? "—" : q.source_refs.map((r: any) => (
                  <div key={r.chunk_id} title={`document ${r.document_id} · chunk ${r.chunk_id}`}>
                    {r.title ?? r.source_uri} <span className="text-gray-400">({r.visibility}, chunk {String(r.chunk_id).slice(0, 8)})</span>
                  </div>
                ))}
              </td>
            </tr>
          ))}
        </Table>
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
  useEffect(() => { if (!running) qc.invalidateQueries({ queryKey: ["job-applications", job.id] }); }, [running]); // eslint-disable-line
  const recompute = useMutation({
    mutationFn: () => api.post(`/matching/jobs/${job.id}/recompute`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["matching-status", job.id] }),
  });
  return (
    <Card title="Candidates" actions={<Button variant="secondary" onClick={() => recompute.mutate()} disabled={recompute.isPending || running}>{running ? "Recomputing…" : "Recompute matches"}</Button>}>
      {isLoading && <Loading />}
      <ErrorBox error={error || recompute.error} onRetry={refetch} />
      {data?.length === 0 && <Empty>No applications yet.</Empty>}
      {data?.length > 0 && (
        <Table head={["Candidate", "Status", "Match", "Applied", ""]}>
          {data.map((a: any) => (
            <tr key={a.id}>
              <td className="py-2 pr-3">{a.student_name}</td>
              <td className="pr-3"><Badge>{a.status}</Badge></td>
              <td className="pr-3">{a.match_score == null ? <span className="text-xs text-gray-400">not computed</span> : pct(a.match_score, 1)}</td>
              <td className="pr-3 text-xs text-gray-500">{a.applied_at ? new Date(a.applied_at).toLocaleString() : ""}</td>
              <td><Link className="text-sm underline" to={`/company/applications/${a.id}`}>Review</Link></td>
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
  const plan = useQuery({ queryKey: ["interview-template", job.id], queryFn: () => api.get(`/interviews/templates/by-job/${job.id}`).then((r) => r.data),
    refetchInterval: (q) => (q.state.data?.status === "PREPARING" ? 3000 : false) });
  const rebuild = useMutation({ mutationFn: () => api.post(`/interviews/templates/by-job/${job.id}/rebuild`), onSuccess: () => qc.invalidateQueries({ queryKey: ["interview-template", job.id] }) });
  const t = plan.data;
  const count = (skill: string, d: string) => (t?.questions ?? []).filter((q: any) => q.skill === skill && q.difficulty === d).length;
  return (
    <Card title="Interview plan" actions={t ? <Badge>{t.status}</Badge> : null}>
      {!t && <Empty>Prepared automatically when you publish the assessment.</Empty>}
      {t && (
        <div className="space-y-2 text-sm" data-testid="interview-plan">
          <p className="text-xs text-gray-600">Every candidate is interviewed against the same competencies and rubric ({t.config.rubric.version}); questions come from the prepared pool
            (question bank first, then knowledge-grounded generation), so no question is invented while a candidate waits. {t.config.min_questions}–{t.config.max_questions} questions, about {t.config.recommended_minutes} minutes.</p>
          {t.status === "PREPARING" && <p className="text-amber-700 text-xs">Preparing questions…</p>}
          {t.error && <p className="text-red-600 text-xs">{t.error}</p>}
          <Table head={["Competency", "Importance", "Required", "Easy", "Medium", "Hard"]}>{t.config.competencies.map((c: any) => (
            <tr key={c.skill_id}><td className="py-1 pr-3">{c.name}</td><td className="pr-3">{c.importance}</td><td className="pr-3">{c.required ? "yes" : "no"}</td>
              {["easy", "medium", "hard"].map((d) => <td key={d} className="pr-3">{count(c.name, d) || "—"}</td>)}</tr>))}</Table>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={() => setOpen((v) => !v)}>{open ? "Hide questions" : `Review ${t.questions.length} questions`}</Button>
            <Button variant="secondary" onClick={() => rebuild.mutate()} disabled={rebuild.isPending || t.status === "PREPARING"}>Rebuild pool</Button>
          </div>
          {open && <ul className="text-xs space-y-1">{t.questions.map((q: any) => (
            <li key={q.id}><Badge tone="gray">{q.skill} · {q.difficulty}</Badge> {q.question_text} <span className="text-gray-400">({q.source === "question_bank" ? "question bank" : "generated"})</span></li>))}</ul>}
          <ErrorBox error={rebuild.error} />
        </div>)}
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
    onSuccess: () => { setEdit(false); qc.invalidateQueries({ queryKey: ["job", job.id] }); qc.invalidateQueries({ queryKey: ["jobs-org"] }); },
  });
  const missing = [!job.employment_type && "employment type", !job.work_mode && "work mode",
    (job.work_mode === "ONSITE" || job.work_mode === "HYBRID") && !(job.location_city && job.location_country) && "city and country"].filter(Boolean);
  return (
    <Card title="Posting details" actions={!edit ? <Button variant="secondary" onClick={() => { setF(fromJob(job)); setEdit(true); }}>{published ? "Extend deadline / openings" : "Edit"}</Button> : null}>
      {!edit ? (
        <div className="space-y-1" data-testid="posting-summary">
          <JobFacts job={job} />
          {missing.length > 0 && <p className="text-xs text-amber-700" data-testid="posting-missing">Add {missing.join(", ")} before publishing.</p>}
          {!job.display?.headline && !job.display?.compensation && <p className="text-xs text-gray-500">No posting details yet.</p>}
        </div>
      ) : (
        <div className="space-y-3">
          {published && <p className="text-xs text-gray-500">This job is published: only the application deadline and the number of openings can change.</p>}
          <PostingFormFields f={f} set={(p) => setF((x) => ({ ...x, ...p }))} lockedExceptDeadline={published} />
          <div className="flex gap-2">
            <Button onClick={() => save.mutate()} disabled={save.isPending || problems(f).length > 0}>{save.isPending ? "Saving…" : "Save posting details"}</Button>
            <Button variant="secondary" onClick={() => setEdit(false)}>Cancel</Button>
          </div>
          <ErrorBox error={save.error} />
        </div>
      )}
    </Card>
  );
}

const APPROVAL_LABEL: Record<string, string> = {
  NOT_REQUIRED: "Not submitted yet (goes to the placement officer when you publish)", PENDING: "Waiting for the placement officer's approval",
  APPROVED: "Approved: visible to eligible students", REJECTED: "Rejected by the placement officer" };

function DistributionCard({ job }: { job: any }) {
  const qc = useQueryClient();
  const dir = useQuery({ queryKey: ["institution-directory"], queryFn: () => api.get("/institutions/directory").then((r) => r.data) });
  const [type, setType] = useState<string>(job.distribution_type ?? "OPEN_MARKET");
  const [inst, setInst] = useState<string>(job.target_institution_id ?? "");
  const save = useMutation({
    mutationFn: () => api.put(`/jobs/${job.id}/distribution`, { distribution_type: type, institution_id: type === "INSTITUTION" ? inst : null }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["job", job.id] }),
  });
  const locked = job.institution_approval === "APPROVED";
  return (
    <Card title="Distribution" actions={job.distribution_type === "INSTITUTION" ? <Badge>{job.institution_approval === "NOT_REQUIRED" ? "NOT SUBMITTED" : job.institution_approval}</Badge> : <Badge>OPEN MARKET</Badge>}>
      <div className="flex gap-2 items-center text-sm">
        <select className={inputCls} value={type} disabled={locked} onChange={(e) => setType(e.target.value)} data-testid="distribution-type">
          <option value="OPEN_MARKET">Open market: every student</option><option value="INSTITUTION">Partner institution (needs approval)</option></select>
        {type === "INSTITUTION" && (
          <select className={inputCls} value={inst} disabled={locked} onChange={(e) => setInst(e.target.value)} data-testid="distribution-institution">
            <option value="">Choose institution…</option>{(dir.data ?? []).map((i: any) => <option key={i.id} value={i.id}>{i.name}</option>)}</select>)}
        <Button variant="secondary" onClick={() => save.mutate()} disabled={locked || save.isPending || (type === "INSTITUTION" && !inst)}>Save</Button>
      </div>
      {job.distribution_type === "INSTITUTION" && <p className="text-xs text-gray-600" data-testid="approval-state">{job.target_institution_name}: {APPROVAL_LABEL[job.institution_approval]}</p>}
      <ErrorBox error={save.error} />
    </Card>
  );
}

export default function CompanyJobDetailPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const [jdText, setJdText] = useState("");
  const [file, setFile] = useState<File | null>(null);

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
    if (processing?.jd?.status === "COMPLETED" || processing?.jd?.status === "FAILED") qc.invalidateQueries({ queryKey: ["job", jobId] });
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
    onSuccess: () => { setJdText(""); setFile(null); qc.invalidateQueries({ queryKey: ["processing", jobId] }); qc.invalidateQueries({ queryKey: ["job", jobId] }); },
  });

  if (isLoading) return <Loading />;
  if (error) return <ErrorBox error={error} onRetry={refetch} />;
  if (!job) return null;
  const jd = processing?.jd;
  const jdBusy = jd && ["PENDING", "RUNNING"].includes(jd.status);

  return (
    <div className="max-w-5xl space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <Link to="/company" className="text-xs text-gray-500 underline">← Jobs</Link>
          <h1 className="text-lg font-semibold text-gray-900">{job.title}</h1>
          <p className="text-xs text-gray-500">{job.organization_name}</p>
        </div>
        <Badge>{job.status}</Badge>
      </div>

      {["DRAFT", "SKILLS_EXTRACTED"].includes(job.status) && (
        <Card title="Job description">
          {job.description_raw && <p className="text-xs text-gray-500 whitespace-pre-wrap max-h-40 overflow-auto border border-gray-100 rounded p-2">{job.description_raw}</p>}
          <textarea className={inputCls} rows={7} placeholder="Paste the job description…" value={jdText} onChange={(e) => setJdText(e.target.value)} />
          <div className="flex items-center gap-3 text-sm">
            <span className="text-gray-500">or upload PDF/DOCX/TXT</span>
            <input type="file" accept=".pdf,.docx,.txt" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          </div>
          <Button onClick={() => analyze.mutate()} disabled={analyze.isPending || jdBusy || (!jdText.trim() && !file && !job.description_raw)}>
            {jdBusy ? "Analyzing…" : job.status === "SKILLS_EXTRACTED" ? "Re-analyze" : "Analyze with AI"}
          </Button>
          {jdBusy && <p className="text-sm text-amber-700">Extracting requirements… ({jd.status})</p>}
          {jd?.status === "FAILED" && <ErrorBox error={{ message: `JD processing failed: ${jd.error}` }} onRetry={() => analyze.mutate()} />}
          <ErrorBox error={analyze.error} />
        </Card>
      )}

      <PostingCard key={job.updated_at ?? job.id + job.status} job={job} />
      <DistributionCard job={job} />
      {job.skills.length > 0 || job.status !== "DRAFT" ? <RequirementsEditor job={job} /> : null}
      {job.status !== "DRAFT" && job.status !== "SKILLS_EXTRACTED" && <AssessmentPanel job={job} processing={processing} />}
      {job.status === "PUBLISHED" && <InterviewPlanCard job={job} />}
      {job.status === "PUBLISHED" && <Candidates job={job} />}
    </div>
  );
}
