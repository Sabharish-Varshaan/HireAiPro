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
  inputCls,
  pct,
} from "../../components/ui";
import { JobFacts } from "../../components/JobSummary";
import HiringProcessPanel from "./HiringProcessPanel";
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
          { id: "assessment", label: "Hiring Process" },
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
          <HiringProcessPanel job={job} />
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
