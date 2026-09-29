import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls, pct } from "../../components/ui";

type Req = {
  id?: string; skill_id: string | null; raw_skill_name: string; canonical_name?: string | null;
  requirement_type: "required" | "preferred"; minimum_level: number; importance: number;
  extraction_confidence?: number; evidence_text?: string | null; delete?: boolean;
};

const EDITABLE = ["DRAFT", "SKILLS_EXTRACTED", "REQUIREMENTS_CONFIRMED"];

function SkillPicker({ onPick }: { onPick: (s: { id: string; canonical_name: string }) => void }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["skill-search", q],
    queryFn: () => api.get("/skills", { params: { q, limit: 8 } }).then((r) => r.data),
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <input className={inputCls} placeholder="Search canonical skill…" value={q} onChange={(e) => setQ(e.target.value)} />
      {q.length >= 2 && data && (
        <div className="absolute z-10 bg-white border border-gray-200 rounded-md mt-1 w-full shadow-sm max-h-56 overflow-auto">
          {data.length === 0 && <p className="text-xs text-gray-500 p-2">No canonical skill matches “{q}”.</p>}
          {data.map((s: { id: string; canonical_name: string; category: string }) => (
            <button key={s.id} className="block w-full text-left text-sm px-2 py-1 hover:bg-gray-50"
              onClick={() => { onPick(s); setQ(""); }}>
              {s.canonical_name} <span className="text-xs text-gray-400">{s.category}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

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
  const generate = useMutation({
    mutationFn: () => api.post(`/assessments/jobs/${job.id}/generate`, { title: `${job.title} Assessment` }),
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
      {gen && (gen.status === "PENDING" || gen.status === "RUNNING") && (
        <p className="text-sm text-amber-700">Generating (Assessment Agent)… this can take a few minutes. Status: {gen.status}</p>
      )}
      {gen?.status === "FAILED" && <ErrorBox error={{ message: `Generation failed: ${gen.error}` }} onRetry={() => generate.mutate()} />}
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

      {job.skills.length > 0 || job.status !== "DRAFT" ? <RequirementsEditor job={job} /> : null}
      {job.status !== "DRAFT" && job.status !== "SKILLS_EXTRACTED" && <AssessmentPanel job={job} processing={processing} />}
      {job.status === "PUBLISHED" && <Candidates job={job} />}
    </div>
  );
}
