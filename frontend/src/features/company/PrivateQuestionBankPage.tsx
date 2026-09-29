import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client";
import { SkillPicker } from "../../components/SkillPicker";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";

const TONE: Record<string, string> = { READY: "green", WARNING: "amber", INVALID: "red", DUPLICATE: "gray", NEEDS_SKILL_MAPPING: "amber" };
const STATUS_LABEL: Record<string, string> = { READY: "Ready", WARNING: "Warning", INVALID: "Invalid", DUPLICATE: "Duplicate", NEEDS_SKILL_MAPPING: "Needs skill mapping" };
const TYPE_LABEL: Record<string, string> = { MCQ: "MCQ", TECHNICAL: "Written", TECHNICAL_WRITTEN: "Written" };

async function download(url: string, params: Record<string, string>, fallback: string) {
  const r = await api.get(url, { params, responseType: "blob" });
  const name = /filename="?([^"]+)"?/.exec(r.headers["content-disposition"] ?? "")?.[1] ?? fallback;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(r.data); a.download = name; a.click(); URL.revokeObjectURL(a.href);
}

function Coverage({ jobId }: { jobId: string }) {
  const cov = useQuery({ queryKey: ["question-coverage", jobId], queryFn: () => api.get("/question-imports/coverage", { params: { job_id: jobId } }).then((r) => r.data) });
  if (cov.isLoading) return <Loading />;
  const c = cov.data;
  return (
    <Card title="Coverage" actions={c?.coverage_percentage != null ? <Badge>{`${c.covered} / ${c.needed} slots`}</Badge> : null}>
      {c?.note && <Empty>{c.note}</Empty>}
      {c?.rows?.length > 0 && (
        <>
          <Table head={["Skill", "Type", "Needed", "Your private questions", "Platform (approved)", "Selected"]}>{c.rows.map((r: any, i: number) => (
            <tr key={i}><td className="py-1 pr-3">{r.skill}</td><td className="pr-3">{TYPE_LABEL[r.type] ?? r.type}</td><td className="pr-3">{r.needed}</td>
              <td className="pr-3">{r.available_private}</td><td className="pr-3">{r.available_platform}</td><td>{r.selected}</td></tr>))}</Table>
          <p className="text-xs text-gray-600" data-testid="coverage-summary">Coverage: {c.covered} / {c.needed}. {c.gap > 0 ? `${c.gap} slot${c.gap > 1 ? "s" : ""} will need AI generation and review.` : "Every slot can be filled from existing questions; AI generation is not needed."} Your private questions are used first, then approved platform questions, then AI.</p>
        </>)}
    </Card>
  );
}

function ImportPanel({ jobId }: { jobId: string }) {
  const qc = useQueryClient();
  const [batch, setBatch] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const upload = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append("file", file); return api.post("/question-imports", fd, { params: { job_id: jobId } }).then((r) => r.data); },
    onSuccess: (b) => { setBatch(b); setDone(null); },
  });
  const patch = useMutation({
    mutationFn: ({ row, body }: { row: number; body: any }) => api.patch(`/question-imports/${batch.id}/rows/${row}`, body).then((r) => r.data),
    onSuccess: setBatch,
  });
  const confirm = useMutation({
    mutationFn: () => api.post(`/question-imports/${batch.id}/confirm`).then((r) => r.data),
    onSuccess: (d) => { setDone(d); setBatch(null); qc.invalidateQueries({ queryKey: ["my-questions"] }); qc.invalidateQueries({ queryKey: ["question-coverage"] }); },
  });
  const [tplErr, setTplErr] = useState<string | null>(null);
  const tpl = (format: string) => download("/question-imports/template", { job_id: jobId, format }, `questions-template.${format}`).catch(() => setTplErr("Could not download the template"));
  return (
    <Card title="Import questions">
      <p className="text-xs text-gray-500">Download a template for this job, fill it in, upload it, review the preview, then confirm. Imported questions are private to your company. MCQ and written questions are supported.</p>
      <div className="flex flex-wrap gap-2 items-center">
        <Button variant="secondary" onClick={() => tpl("xlsx")}>Download Excel template</Button>
        <Button variant="secondary" onClick={() => tpl("csv")}>CSV</Button>
        <Button variant="secondary" onClick={() => tpl("json")}>JSON</Button>
        <input type="file" accept=".xlsx,.csv,.json" data-testid="import-file" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
        {upload.isPending && <span className="text-xs text-gray-500">Validating…</span>}
      </div>
      {tplErr && <p className="text-xs text-red-600">{tplErr}</p>}
      <ErrorBox error={upload.error || patch.error || confirm.error} />
      {done && <p className="text-sm text-green-700" data-testid="import-done">Imported {done.imported} question{done.imported === 1 ? "" : "s"} into your private bank{done.skipped_duplicates ? ` (${done.skipped_duplicates} duplicate skipped)` : ""}.</p>}
      {batch && (
        <div className="space-y-2" data-testid="import-preview">
          <p className="text-sm">{batch.filename}: <b>{batch.valid_rows}</b> ready to import, <b className={batch.invalid_rows ? "text-red-600" : ""}>{batch.invalid_rows}</b> need attention, <b>{batch.duplicate_rows}</b> duplicate, of {batch.total_rows} rows.</p>
          <div className="overflow-x-auto">
            <Table head={["Row", "Type", "Skill (as entered)", "Canonical skill", "Difficulty", "Question", "Status", "Duplicate", "Action"]}>{batch.rows.map((r: any) => (
              <tr key={r.row} className={r.excluded ? "opacity-40" : r.status === "INVALID" ? "bg-red-50" : ""} data-status={r.status}>
                <td className="py-1 pr-2">{r.row}</td><td className="pr-2">{TYPE_LABEL[r.question_type] ?? r.raw.question_type ?? "—"}</td><td className="pr-2">{r.raw.skill || "—"}</td>
                <td className="pr-2">{r.canonical_skill ?? "—"}</td><td className="pr-2">{r.difficulty ?? "—"}</td>
                <td className="pr-2 max-w-xs"><span className="line-clamp-2">{r.raw.question_text}</span>
                  {r.issues.filter((i: any) => i.level !== "info").map((i: any, k: number) => <span key={k} className={`block text-[11px] ${i.level === "error" ? "text-red-600" : "text-amber-700"}`}>{i.message}</span>)}</td>
                <td className="pr-2"><Badge tone={TONE[r.status]}>{STATUS_LABEL[r.status] ?? r.status}</Badge></td>
                <td className="pr-2 text-xs">{r.duplicate_of ? `in ${r.duplicate_of.where}${r.duplicate_of.row ? ` (row ${r.duplicate_of.row})` : ""}` : "—"}</td>
                <td className="space-y-1 min-w-[10rem]">
                  {r.status === "NEEDS_SKILL_MAPPING" && !r.excluded && <SkillPicker onPick={(s) => patch.mutate({ row: r.row, body: { skill_id: s.id } })} />}
                  <button className="text-xs underline text-gray-600" onClick={() => patch.mutate({ row: r.row, body: { excluded: !r.excluded } })}>{r.excluded ? "Include" : "Exclude"}</button>
                </td>
              </tr>))}</Table>
          </div>
          <div className="flex gap-2">
            <Button onClick={() => confirm.mutate()} disabled={confirm.isPending || batch.valid_rows === 0}>{confirm.isPending ? "Importing…" : `Confirm import (${batch.valid_rows})`}</Button>
            <Button variant="secondary" onClick={() => { api.post(`/question-imports/${batch.id}/cancel`); setBatch(null); }}>Discard</Button>
          </div>
        </div>)}
    </Card>
  );
}

function AddQuestion({ orgId, onDone }: { orgId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({ type: "MCQ", skill: "", difficulty: "medium", text: "", options: "", correct: "A", rubric: "" });
  const add = useMutation({
    mutationFn: () => {
      const opts = f.options.split("\n").map((o) => o.trim()).filter(Boolean);
      const body: any = { organization_id: orgId, question_text: f.text, question_type: f.type, skill: f.skill, difficulty: f.difficulty };
      if (f.type === "MCQ") { body.options = opts; body.correct_option = "ABCDE".indexOf(f.correct); } else { body.rubric = { criteria: f.rubric.split("\n").map((x) => x.trim()).filter(Boolean), version: "rubric_v1" }; body.expected_concepts = body.rubric.criteria; }
      return api.post("/questions", body).then((r) => r.data);
    },
    onSuccess: () => { setOpen(false); setF({ ...f, text: "", options: "", rubric: "" }); onDone(); },
  });
  if (!open) return <Button variant="secondary" onClick={() => setOpen(true)}>Add question</Button>;
  return (
    <Card title="Add a question">
      <div className="grid grid-cols-3 gap-2">
        <select className={inputCls} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}><option value="MCQ">MCQ</option><option value="TECHNICAL">Written</option></select>
        <input className={inputCls} placeholder="Skill (e.g. Python)" value={f.skill} onChange={(e) => setF({ ...f, skill: e.target.value })} />
        <select className={inputCls} value={f.difficulty} onChange={(e) => setF({ ...f, difficulty: e.target.value })}><option>easy</option><option>medium</option><option>hard</option></select>
      </div>
      <textarea className={inputCls} rows={3} placeholder="Question text" value={f.text} onChange={(e) => setF({ ...f, text: e.target.value })} />
      {f.type === "MCQ" ? (
        <div className="grid grid-cols-4 gap-2"><textarea className={`${inputCls} col-span-3`} rows={4} placeholder="One option per line (2–5)" value={f.options} onChange={(e) => setF({ ...f, options: e.target.value })} />
          <select className={inputCls} value={f.correct} onChange={(e) => setF({ ...f, correct: e.target.value })}>{"ABCDE".split("").map((l) => <option key={l}>{l}</option>)}</select></div>
      ) : <textarea className={inputCls} rows={3} placeholder="Grading criteria, one per line (at least 2)" value={f.rubric} onChange={(e) => setF({ ...f, rubric: e.target.value })} />}
      <div className="flex gap-2"><Button onClick={() => add.mutate()} disabled={add.isPending || !f.text || !f.skill}>Save to private bank</Button><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button></div>
      <ErrorBox error={add.error} />
      {add.data && (add.data.errors?.length > 0 || add.data.duplicates?.length > 0) && <p className="text-xs text-amber-700">{add.data.errors?.[0]?.error ?? "Duplicate of an existing question."}</p>}
    </Card>
  );
}

function Browse({ orgId, assessment }: { orgId: string; assessment: any }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const list = useQuery({ queryKey: ["my-questions", orgId, q, type], queryFn: () => api.get("/questions", { params: { organization_id: orgId, q: q || undefined, question_type: type || undefined } }).then((r) => r.data) });
  const detail = useQuery({ queryKey: ["assessment-detail", assessment?.id], enabled: !!assessment?.id, queryFn: () => api.get(`/assessments/${assessment.id}`).then((r) => r.data) });
  const inAssessment = new Set((detail.data?.sections ?? []).flatMap((s: any) => s.questions.map((x: any) => x.question.id)));
  const canEdit = assessment && assessment.status !== "PUBLISHED";
  const refresh = () => { qc.invalidateQueries({ queryKey: ["assessment-detail"] }); qc.invalidateQueries({ queryKey: ["question-coverage"] }); };
  const attach = useMutation({ mutationFn: (id: string) => api.post(`/assessments/${assessment.id}/questions`, { question_id: id }), onSuccess: refresh });
  const detach = useMutation({ mutationFn: (id: string) => api.delete(`/assessments/${assessment.id}/questions/${id}`), onSuccess: refresh });
  const mine = (list.data ?? []).filter((x: any) => x.organization_id === orgId); // the list also carries approved platform questions; this page is about the company's own
  return (
    <Card title="My questions">
      <div className="flex gap-2"><input className={inputCls} placeholder="Search my questions" value={q} onChange={(e) => setQ(e.target.value)} data-testid="browse-search" />
        <select className={`${inputCls} w-40`} value={type} onChange={(e) => setType(e.target.value)}><option value="">All types</option><option value="MCQ">MCQ</option><option value="TECHNICAL">Written</option></select></div>
      {list.isLoading && <Loading />}
      {!list.isLoading && mine.length === 0 && <Empty>No private questions yet. Import or add some above.</Empty>}
      {!assessment && <p className="text-xs text-amber-700">Generate the assessment draft on the job page to attach questions to it.</p>}
      <ul className="divide-y divide-gray-100 text-sm" data-testid="my-questions">
        {mine.map((x: any) => (
          <li key={x.id} className="py-2 flex items-start gap-3">
            <div className="flex-1"><p>{x.question_text}</p>
              <p className="text-xs text-gray-500">{TYPE_LABEL[x.question_type] ?? x.question_type} · {x.skill_name} · {x.difficulty} · {x.provenance ? x.provenance.replaceAll("_", " ").toLowerCase() : "private"}</p></div>
            {canEdit && (inAssessment.has(x.id)
              ? <Button variant="secondary" onClick={() => detach.mutate(x.id)}>Remove from assessment</Button>
              : <Button variant="secondary" onClick={() => attach.mutate(x.id)} disabled={attach.isPending}>Add to assessment</Button>)}
            {!canEdit && assessment && inAssessment.has(x.id) && <Badge>In assessment</Badge>}
          </li>))}
      </ul>
      <ErrorBox error={attach.error || detach.error} />
    </Card>
  );
}

export default function PrivateQuestionBankPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data) });
  const assessment = useQuery({ queryKey: ["assessment-by-job", jobId], queryFn: () => api.get(`/assessments/by-job/${jobId}`).then((r) => r.data) });
  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} />;
  return (
    <div className="max-w-5xl space-y-4">
      <div><Link to={`/company/jobs/${jobId}`} className="text-xs text-gray-500 underline">← {job.data.title}</Link>
        <h1 className="text-lg font-semibold">Private question bank</h1>
        <p className="text-xs text-gray-500">Only {job.data.organization_name} can see, search or reuse these questions. Use them across all your jobs.</p></div>
      <Coverage jobId={jobId!} />
      <div className="flex gap-2"><AddQuestion orgId={job.data.organization_id} onDone={() => { qc.invalidateQueries({ queryKey: ["my-questions"] }); qc.invalidateQueries({ queryKey: ["question-coverage"] }); }} /></div>
      <ImportPanel jobId={jobId!} />
      <Browse orgId={job.data.organization_id} assessment={assessment.data} />
    </div>
  );
}
