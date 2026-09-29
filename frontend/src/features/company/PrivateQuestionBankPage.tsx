import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { SkillPicker } from "../../components/SkillPicker";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  PageHeader,
  Table,
  inputCls,
} from "../../components/ui";

const TONE: Record<string, string> = {
  READY: "green",
  WARNING: "amber",
  INVALID: "red",
  DUPLICATE: "gray",
  NEEDS_SKILL_MAPPING: "amber",
};
const STATUS_LABEL: Record<string, string> = {
  READY: "Ready",
  WARNING: "Warning",
  INVALID: "Invalid",
  DUPLICATE: "Duplicate",
  NEEDS_SKILL_MAPPING: "Needs skill mapping",
};
const TYPE_LABEL: Record<string, string> = {
  MCQ: "MCQ",
  TECHNICAL: "Written",
  TECHNICAL_WRITTEN: "Written",
};

async function download(url: string, params: Record<string, string>, fallback: string) {
  const r = await api.get(url, { params, responseType: "blob" });
  const name =
    /filename="?([^"]+)"?/.exec(r.headers["content-disposition"] ?? "")?.[1] ?? fallback;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(r.data);
  a.download = name;
  a.click();
  URL.revokeObjectURL(a.href);
}

function Coverage({ jobId }: { jobId: string }) {
  const cov = useQuery({
    queryKey: ["question-coverage", jobId],
    queryFn: () => api.get("/question-imports/coverage", { params: { job_id: jobId } }).then((r) => r.data),
  });
  if (cov.isLoading) return <Loading />;
  const c = cov.data;
  return (
    <Card
      title="Slot Coverage for this Job"
      description="Private questions are mapped against the required competency blueprint."
      actions={
        c?.coverage_percentage != null ? (
          <Badge tone={c.covered === c.needed ? "green" : "amber"}>
            {`${c.covered} / ${c.needed} slots covered`}
          </Badge>
        ) : null
      }
    >
      {c?.note && <Empty>{c.note}</Empty>}
      {c?.rows?.length > 0 && (
        <div className="space-y-3">
          <Table head={["Competency", "Type", "Slots Needed", "Your Private Questions", "Platform Approved", "Selected"]}>
            {c.rows.map((r: any, i: number) => (
              <tr key={i} className="hover:bg-gray-50/50">
                <td className="py-2 pr-3 font-medium text-gray-900">{r.skill}</td>
                <td className="pr-3">
                  <Badge tone="gray">{TYPE_LABEL[r.type] ?? r.type}</Badge>
                </td>
                <td className="pr-3 text-xs font-semibold">{r.needed}</td>
                <td className="pr-3 text-xs font-medium text-blue-700">{r.available_private}</td>
                <td className="pr-3 text-xs text-gray-600">{r.available_platform}</td>
                <td className="pr-3 text-xs font-semibold text-emerald-700">{r.selected}</td>
              </tr>
            ))}
          </Table>
          <p className="text-xs text-gray-600 bg-gray-50 p-2.5 rounded-lg border border-gray-100" data-testid="coverage-summary">
            <strong>Coverage Summary:</strong> {c.covered} / {c.needed}.{" "}
            {c.gap > 0
              ? `${c.gap} slot${c.gap > 1 ? "s" : ""} will need AI generation and review.`
              : "Every slot can be filled from existing questions; AI generation is not needed."}{" "}
            Your private questions are prioritized first, then platform questions, then AI generation.
          </p>
        </div>
      )}
    </Card>
  );
}

function ImportPanel({ jobId }: { jobId: string }) {
  const qc = useQueryClient();
  const [batch, setBatch] = useState<any>(null);
  const [done, setDone] = useState<any>(null);
  const upload = useMutation({
    mutationFn: (file: File) => {
      const fd = new FormData();
      fd.append("file", file);
      return api.post("/question-imports", fd, { params: { job_id: jobId } }).then((r) => r.data);
    },
    onSuccess: (b) => {
      setBatch(b);
      setDone(null);
    },
  });
  const patch = useMutation({
    mutationFn: ({ row, body }: { row: number; body: any }) =>
      api.patch(`/question-imports/${batch.id}/rows/${row}`, body).then((r) => r.data),
    onSuccess: setBatch,
  });
  const confirm = useMutation({
    mutationFn: () => api.post(`/question-imports/${batch.id}/confirm`).then((r) => r.data),
    onSuccess: (d) => {
      setDone(d);
      setBatch(null);
      qc.invalidateQueries({ queryKey: ["my-questions"] });
      qc.invalidateQueries({ queryKey: ["question-coverage"] });
    },
  });
  const [tplErr, setTplErr] = useState<string | null>(null);
  const tpl = (format: string) =>
    download("/question-imports/template", { job_id: jobId, format }, `questions-template.${format}`).catch(() =>
      setTplErr("Could not download the template")
    );

  return (
    <Card
      title="Import Questions via Spreadsheet"
      description="Download a pre-formatted template for this job, fill it in, preview the mapped rows, and confirm."
    >
      <div className="space-y-3">
        <div className="flex flex-wrap gap-2 items-center">
          <Button variant="secondary" size="sm" onClick={() => tpl("xlsx")}>
            📥 Download Excel template (.xlsx)
          </Button>
          <Button variant="secondary" size="sm" onClick={() => tpl("csv")}>
            CSV template
          </Button>
          <Button variant="secondary" size="sm" onClick={() => tpl("json")}>
            JSON template
          </Button>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs text-gray-500">Upload filled file:</span>
            <input
              type="file"
              accept=".xlsx,.csv,.json"
              className="text-xs"
              data-testid="import-file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) upload.mutate(f);
                e.target.value = "";
              }}
            />
          </div>
          {upload.isPending && <span className="text-xs text-amber-700">Validating spreadsheet…</span>}
        </div>
        {tplErr && <p className="text-xs text-red-600">{tplErr}</p>}
        <ErrorBox error={upload.error || patch.error || confirm.error} />
        {done && (
          <p className="text-sm font-medium text-emerald-800 bg-emerald-50 p-2.5 rounded border border-emerald-200" data-testid="import-done">
            ✓ Successfully imported {done.imported} question{done.imported === 1 ? "" : "s"} into your private bank
            {done.skipped_duplicates ? ` (${done.skipped_duplicates} duplicate skipped)` : ""}.
          </p>
        )}
        {batch && (
          <div className="space-y-3 pt-2" data-testid="import-preview">
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-xs text-blue-900">
              <strong>{batch.filename}:</strong> <b>{batch.valid_rows}</b> ready to import,{" "}
              <b className={batch.invalid_rows ? "text-red-600" : ""}>{batch.invalid_rows}</b> need attention,{" "}
              <b>{batch.duplicate_rows}</b> duplicate, out of {batch.total_rows} total rows.
            </div>
            <div className="overflow-x-auto">
              <Table head={["Row", "Type", "Skill (raw)", "Canonical", "Diff.", "Question", "Status", "Duplicate", "Action"]}>
                {batch.rows.map((r: any) => (
                  <tr
                    key={r.row}
                    className={`hover:bg-gray-50/50 ${r.excluded ? "opacity-40" : r.status === "INVALID" ? "bg-red-50/50" : ""}`}
                    data-status={r.status}
                  >
                    <td className="py-2 pr-2 text-xs font-mono">{r.row}</td>
                    <td className="pr-2 text-xs">
                      <Badge tone="gray">{TYPE_LABEL[r.question_type] ?? r.raw.question_type ?? "—"}</Badge>
                    </td>
                    <td className="pr-2 text-xs text-gray-700">{r.raw.skill || "—"}</td>
                    <td className="pr-2 text-xs font-medium text-gray-900">{r.canonical_skill ?? "—"}</td>
                    <td className="pr-2 text-xs">{r.difficulty ?? "—"}</td>
                    <td className="pr-2 max-w-xs">
                      <span className="line-clamp-2 text-xs text-gray-800">{r.raw.question_text}</span>
                      {r.issues
                        .filter((i: any) => i.level !== "info")
                        .map((i: any, k: number) => (
                          <span key={k} className={`block text-[11px] ${i.level === "error" ? "text-red-600" : "text-amber-700"}`}>
                            {i.message}
                          </span>
                        ))}
                    </td>
                    <td className="pr-2">
                      <Badge tone={TONE[r.status]}>{STATUS_LABEL[r.status] ?? r.status}</Badge>
                    </td>
                    <td className="pr-2 text-xs text-gray-500">
                      {r.duplicate_of ? `in ${r.duplicate_of.where}${r.duplicate_of.row ? ` (row ${r.duplicate_of.row})` : ""}` : "—"}
                    </td>
                    <td className="space-y-1 min-w-[10rem]">
                      {r.status === "NEEDS_SKILL_MAPPING" && !r.excluded && (
                        <SkillPicker onPick={(s) => patch.mutate({ row: r.row, body: { skill_id: s.id } })} />
                      )}
                      <button
                        className="text-xs underline text-gray-600 hover:text-gray-900 block"
                        onClick={() => patch.mutate({ row: r.row, body: { excluded: !r.excluded } })}
                      >
                        {r.excluded ? "Include" : "Exclude"}
                      </button>
                    </td>
                  </tr>
                ))}
              </Table>
            </div>
            <div className="flex gap-2 pt-2">
              <Button onClick={() => confirm.mutate()} disabled={confirm.isPending || batch.valid_rows === 0}>
                {confirm.isPending ? "Importing…" : `Confirm import (${batch.valid_rows})`}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  api.post(`/question-imports/${batch.id}/cancel`);
                  setBatch(null);
                }}
              >
                Discard
              </Button>
            </div>
          </div>
        )}
      </div>
    </Card>
  );
}

function AddQuestion({ orgId, onDone }: { orgId: string; onDone: () => void }) {
  const [open, setOpen] = useState(false);
  const [f, setF] = useState({
    type: "MCQ",
    skill: "",
    difficulty: "medium",
    text: "",
    options: "",
    correct: "A",
    rubric: "",
  });
  const add = useMutation({
    mutationFn: () => {
      const opts = f.options.split("\n").map((o) => o.trim()).filter(Boolean);
      const body: any = {
        organization_id: orgId,
        question_text: f.text,
        question_type: f.type,
        skill: f.skill,
        difficulty: f.difficulty,
      };
      if (f.type === "MCQ") {
        body.options = opts;
        body.correct_option = "ABCDE".indexOf(f.correct);
      } else {
        body.rubric = {
          criteria: f.rubric.split("\n").map((x) => x.trim()).filter(Boolean),
          version: "rubric_v1",
        };
        body.expected_concepts = body.rubric.criteria;
      }
      return api.post("/questions", body).then((r) => r.data);
    },
    onSuccess: () => {
      setOpen(false);
      setF({ ...f, text: "", options: "", rubric: "" });
      onDone();
    },
  });

  if (!open) {
    return (
      <Button variant="secondary" onClick={() => setOpen(true)}>
        + Add Single Question
      </Button>
    );
  }

  return (
    <Card title="Add a Private Question">
      <div className="space-y-3">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
          <select className={inputCls} value={f.type} onChange={(e) => setF({ ...f, type: e.target.value })}>
            <option value="MCQ">MCQ</option>
            <option value="TECHNICAL">Written</option>
          </select>
          <input
            className={inputCls}
            placeholder="Skill (e.g. Python)"
            value={f.skill}
            onChange={(e) => setF({ ...f, skill: e.target.value })}
          />
          <select className={inputCls} value={f.difficulty} onChange={(e) => setF({ ...f, difficulty: e.target.value })}>
            <option value="easy">Easy</option>
            <option value="medium">Medium</option>
            <option value="hard">Hard</option>
          </select>
        </div>
        <textarea
          className={inputCls}
          rows={3}
          placeholder="Enter the question text…"
          value={f.text}
          onChange={(e) => setF({ ...f, text: e.target.value })}
        />
        {f.type === "MCQ" ? (
          <div className="grid grid-cols-4 gap-2">
            <textarea
              className={`${inputCls} col-span-3`}
              rows={4}
              placeholder="One option per line (2–5 options)"
              value={f.options}
              onChange={(e) => setF({ ...f, options: e.target.value })}
            />
            <div>
              <label className="text-xs text-gray-500 mb-1 block">Correct Option</label>
              <select className={inputCls} value={f.correct} onChange={(e) => setF({ ...f, correct: e.target.value })}>
                {"ABCDE".split("").map((l) => (
                  <option key={l} value={l}>
                    Option {l}
                  </option>
                ))}
              </select>
            </div>
          </div>
        ) : (
          <textarea
            className={inputCls}
            rows={3}
            placeholder="Grading rubric criteria, one per line (at least 2)"
            value={f.rubric}
            onChange={(e) => setF({ ...f, rubric: e.target.value })}
          />
        )}
        <div className="flex gap-2">
          <Button onClick={() => add.mutate()} disabled={add.isPending || !f.text || !f.skill}>
            {add.isPending ? "Saving…" : "Save to private bank"}
          </Button>
          <Button variant="secondary" onClick={() => setOpen(false)}>
            Cancel
          </Button>
        </div>
        <ErrorBox error={add.error} />
        {add.data && (add.data.errors?.length > 0 || add.data.duplicates?.length > 0) && (
          <p className="text-xs text-amber-700 bg-amber-50 p-2 rounded">
            {add.data.errors?.[0]?.error ?? "Duplicate of an existing question."}
          </p>
        )}
      </div>
    </Card>
  );
}

function Browse({ orgId, assessment, jobId }: { orgId: string; assessment: any; jobId: string }) {
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const list = useQuery({
    queryKey: ["my-questions", orgId, q, type],
    queryFn: () =>
      api
        .get("/questions", {
          params: { organization_id: orgId, q: q || undefined, question_type: type || undefined },
        })
        .then((r) => r.data),
  });
  const detail = useQuery({
    queryKey: ["assessment-detail", assessment?.id],
    enabled: !!assessment?.id,
    queryFn: () => api.get(`/assessments/${assessment.id}`).then((r) => r.data),
  });
  const inAssessment = new Set(
    (detail.data?.sections ?? []).flatMap((s: any) => s.questions.map((x: any) => x.question.id))
  );
  const canEdit = !assessment || assessment.status !== "PUBLISHED";
  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["assessment-detail"] });
    qc.invalidateQueries({ queryKey: ["question-coverage"] });
  };
  const attach = useMutation({
    mutationFn: (id: string) => api.post(`/assessments/jobs/${jobId}/questions`, { question_id: id }),
    onSuccess: () => {
      refresh();
      qc.invalidateQueries({ queryKey: ["assessment-by-job"] });
    },
  });
  const detach = useMutation({
    mutationFn: (id: string) => api.delete(`/assessments/${assessment.id}/questions/${id}`),
    onSuccess: refresh,
  });
  const mine = (list.data ?? []).filter((x: any) => x.organization_id === orgId);

  return (
    <Card title="Private Questions in Workspace" description="Manage questions attached to this job's assessment draft.">
      <div className="flex flex-col sm:flex-row gap-2">
        <input
          className={inputCls}
          placeholder="Search private questions…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          data-testid="browse-search"
        />
        <select className={`${inputCls} sm:w-44`} value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All Question Types</option>
          <option value="MCQ">MCQ</option>
          <option value="TECHNICAL">Written</option>
        </select>
      </div>
      {list.isLoading && <Loading />}
      {!list.isLoading && mine.length === 0 && (
        <Empty>No private questions found. Import or add some above.</Empty>
      )}
      <ul className="divide-y divide-gray-100 text-sm" data-testid="my-questions">
        {mine.map((x: any) => (
          <li key={x.id} className="py-3 flex flex-col sm:flex-row sm:items-start justify-between gap-3 hover:bg-gray-50/50 p-2 rounded">
            <div className="flex-1 space-y-1">
              <p className="font-medium text-gray-900 leading-snug">{x.question_text}</p>
              <div className="flex items-center gap-2 text-xs text-gray-500">
                <Badge tone="gray">{TYPE_LABEL[x.question_type] ?? x.question_type}</Badge>
                <span>{x.skill_name}</span>
                <span>•</span>
                <span>{x.difficulty}</span>
                <span>•</span>
                <span className="text-gray-400">{x.provenance ? x.provenance.replaceAll("_", " ").toLowerCase() : "private"}</span>
              </div>
            </div>
            <div className="shrink-0">
              {canEdit &&
                (inAssessment.has(x.id) ? (
                  <Button variant="danger" size="sm" onClick={() => detach.mutate(x.id)}>
                    Remove from assessment
                  </Button>
                ) : (
                  <Button variant="secondary" size="sm" onClick={() => attach.mutate(x.id)} disabled={attach.isPending}>
                    {attach.isPending ? "Adding…" : "Add to assessment"}
                  </Button>
                ))}
              {!canEdit && assessment && inAssessment.has(x.id) && <Badge tone="green">In assessment</Badge>}
            </div>
          </li>
        ))}
      </ul>
      <ErrorBox error={attach.error || detach.error} />
    </Card>
  );
}

export default function PrivateQuestionBankPage() {
  const { jobId } = useParams();
  const qc = useQueryClient();
  const job = useQuery({ queryKey: ["job", jobId], queryFn: () => api.get(`/jobs/${jobId}`).then((r) => r.data) });
  const assessment = useQuery({
    queryKey: ["assessment-by-job", jobId],
    queryFn: () => api.get(`/assessments/by-job/${jobId}`).then((r) => r.data),
  });

  if (job.isLoading) return <Loading />;
  if (job.error) return <ErrorBox error={job.error} />;

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        back={{ label: job.data.title, href: `/company/jobs/${jobId}` }}
        title="Job Question Bank & Import"
        description={`Only ${job.data.organization_name} can view, search, or reuse these questions across jobs.`}
        actions={
          <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
            🔒 Company Private
          </span>
        }
      />
      <Coverage jobId={jobId!} />
      <div className="flex gap-2">
        <AddQuestion
          orgId={job.data.organization_id}
          onDone={() => {
            qc.invalidateQueries({ queryKey: ["my-questions"] });
            qc.invalidateQueries({ queryKey: ["question-coverage"] });
          }}
        />
      </div>
      <ImportPanel jobId={jobId!} />
      <Browse orgId={job.data.organization_id} assessment={assessment.data} jobId={jobId!} />
    </div>
  );
}
