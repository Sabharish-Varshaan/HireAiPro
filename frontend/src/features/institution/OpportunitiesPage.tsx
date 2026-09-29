import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import { EMPLOYMENT_TYPES, WORK_MODES } from "../../lib/posting";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  Loading,
  Modal,
  PageHeader,
  inputCls,
  questionTypeLabel,
} from "../../components/ui";
import { useInstitution } from "./useInstitution";

function OpportunityRow({
  inst,
  op,
  structure,
}: {
  inst: any;
  op: any;
  structure: any;
}) {
  const qc = useQueryClient();
  const [expanded, setExpanded] = useState(op.status === "PENDING");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [deps, setDeps] = useState<string[]>([]);
  const [cohorts, setCohorts] = useState<string[]>([]);
  const [years, setYears] = useState("");
  const [note, setNote] = useState("");

  const done = () => {
    qc.invalidateQueries({ queryKey: ["opportunities"] });
    setRejectOpen(false);
  };
  const approve = useMutation({
    mutationFn: () =>
      api.post(`/institutions/${inst.id}/opportunities/${op.job_id}/approve`, {
        department_ids: deps,
        cohort_ids: cohorts,
        graduation_years: years
          .split(",")
          .map((y) => y.trim())
          .filter(Boolean)
          .map(Number),
      }),
    onSuccess: done,
  });
  const reject = useMutation({
    mutationFn: () => api.post(`/institutions/${inst.id}/opportunities/${op.job_id}/reject`, { note }),
    onSuccess: done,
  });

  const toggle = (arr: string[], set: (v: string[]) => void, id: string) =>
    set(arr.includes(id) ? arr.filter((x) => x !== id) : [...arr, id]);
  const nameOf = (list: any[], id: string) => list.find((x) => x.id === id)?.name ?? id;

  return (
    <div className="bg-white border border-gray-200 rounded-xl overflow-hidden shadow-xs">
      <div className="p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white">
        <div className="space-y-1">
          <div className="flex items-center gap-2.5">
            <h2 className="text-base font-semibold text-gray-900">{op.title}</h2>
            <Badge>{op.status}</Badge>
          </div>
          <p className="text-xs font-medium text-gray-600">{op.company}</p>
          <div className="pt-0.5">
            <JobFacts job={{ display: op.display, number_of_openings: op.number_of_openings }} compact />
          </div>
        </div>

        <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setExpanded((v) => !v)}
          >
            {expanded ? "Hide Details ▲" : "Review Details ▼"}
          </Button>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-gray-100 p-4 bg-gray-50/50 space-y-4 text-xs">
          {op.assessment && (
            <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg text-blue-950 space-y-1" data-testid="op-assessment">
              <span className="font-semibold block">Campus Technical Assessment:</span>
              <p>
                {op.assessment.question_count} questions (
                {Object.entries(op.assessment.types)
                  .map(([t, n]) => `${n} ${questionTypeLabel(t).toLowerCase()}`)
                  .join(", ")}
                ) · {op.assessment.duration_minutes} min duration
              </p>
            </div>
          )}

          {op.description && (
            <div className="space-y-1">
              <span className="font-semibold text-gray-700">Role Description:</span>
              <p className="text-gray-600 whitespace-pre-wrap max-h-36 overflow-auto border border-gray-200 bg-white rounded-lg p-3">
                {op.description}
              </p>
            </div>
          )}

          <div className="space-y-1.5">
            <span className="font-semibold text-gray-700">Required Competencies:</span>
            <div className="flex flex-wrap gap-1.5">
              {op.skills.map((s: any) => (
                <Badge key={s.name} tone={s.type === "required" ? "blue" : "gray"}>
                  {s.name}
                </Badge>
              ))}
            </div>
          </div>

          {op.status === "PENDING" ? (
            <div className="p-4 bg-white border border-gray-200 rounded-xl space-y-3">
              <div>
                <p className="text-xs font-bold text-gray-900">Student Eligibility Rules</p>
                <p className="text-gray-500 text-[11px]">
                  Specify which groups can view and apply for this opportunity. Leave all unselected to grant access to the entire institution.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-1">
                <div className="space-y-1.5">
                  <span className="font-semibold text-gray-700 block">Eligible Departments</span>
                  {structure.departments.length === 0 ? (
                    <span className="text-gray-400">No departments defined</span>
                  ) : (
                    <div className="space-y-1 max-h-32 overflow-y-auto">
                      {structure.departments.map((d: any) => (
                        <label key={d.id} className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="checkbox"
                            className="rounded text-blue-600"
                            checked={deps.includes(d.id)}
                            onChange={() => toggle(deps, setDeps, d.id)}
                          />
                          <span>{d.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <span className="font-semibold text-gray-700 block">Eligible Cohorts</span>
                  {structure.cohorts.length === 0 ? (
                    <span className="text-gray-400">No cohorts defined</span>
                  ) : (
                    <div className="space-y-1 max-h-32 overflow-y-auto">
                      {structure.cohorts.map((c: any) => (
                        <label key={c.id} className="flex items-center gap-1.5 cursor-pointer">
                          <input
                            type="checkbox"
                            className="rounded text-blue-600"
                            checked={cohorts.includes(c.id)}
                            onChange={() => toggle(cohorts, setCohorts, c.id)}
                          />
                          <span>{c.name}</span>
                        </label>
                      ))}
                    </div>
                  )}
                </div>

                <div className="space-y-1.5">
                  <span className="font-semibold text-gray-700 block">Target Graduation Years</span>
                  <input
                    className={inputCls}
                    placeholder="e.g. 2026, 2027"
                    value={years}
                    onChange={(e) => setYears(e.target.value)}
                  />
                  <span className="text-[10px] text-gray-400">Comma-separated year values</span>
                </div>
              </div>

              <div className="flex gap-2 pt-2 border-t border-gray-100">
                <Button onClick={() => approve.mutate()} disabled={approve.isPending}>
                  {approve.isPending ? "Approving…" : "Approve & Publish to Students"}
                </Button>
                <Button variant="danger" onClick={() => setRejectOpen(true)}>
                  Reject Opportunity
                </Button>
              </div>
              <ErrorBox error={approve.error || reject.error} />
            </div>
          ) : op.status === "APPROVED" ? (
            <div className="p-3 bg-emerald-50 border border-emerald-200 rounded-lg text-emerald-900 space-y-0.5">
              <span className="font-semibold block">Distribution Active</span>
              <p>
                Visible to: Departments{" "}
                {(op.eligibility?.department_ids ?? []).map((i: string) => nameOf(structure.departments, i)).join(", ") ||
                  "All"}{" "}
                · Cohorts{" "}
                {(op.eligibility?.cohort_ids ?? []).map((i: string) => nameOf(structure.cohorts, i)).join(", ") ||
                  "All"}{" "}
                · Graduation Years {(op.eligibility?.graduation_years ?? []).join(", ") || "All"}
              </p>
            </div>
          ) : (
            <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-900 space-y-0.5">
              <span className="font-semibold block">Opportunity Rejected</span>
              <p>Reason: {op.note || "No specific note provided"}</p>
            </div>
          )}
        </div>
      )}

      {/* Reject Reason Dialog */}
      <Modal open={rejectOpen} onClose={() => setRejectOpen(false)} title="Reject Opportunity">
        <div className="space-y-3">
          <p className="text-xs text-gray-500">
            Please provide a constructive reason for rejecting this job posting. The company recruiter will see this explanation.
          </p>
          <textarea
            className={inputCls}
            rows={3}
            placeholder="e.g. Role package does not meet institutional placement minimums for this branch."
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setRejectOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => reject.mutate()}
              disabled={reject.isPending || note.trim().length < 3}
            >
              {reject.isPending ? "Rejecting…" : "Confirm Rejection"}
            </Button>
          </div>
          <ErrorBox error={reject.error} />
        </div>
      </Modal>
    </div>
  );
}

export default function OpportunitiesPage() {
  const { inst, isLoading } = useInstitution();
  const [tab, setTab] = useState<"PENDING" | "APPROVED" | "REJECTED">("PENDING");
  const [ftype, setFtype] = useState("");
  const [fmode, setFmode] = useState("");

  const ops = useQuery({
    queryKey: ["opportunities", inst?.id, tab],
    enabled: !!inst,
    queryFn: () =>
      api.get(`/institutions/${inst.id}/opportunities`, { params: { status: tab } }).then((r) => r.data),
  });
  const structure = useQuery({
    queryKey: ["structure", inst?.id],
    enabled: !!inst,
    queryFn: () => api.get(`/institutions/${inst.id}/structure`).then((r) => r.data),
  });

  if (isLoading) return <Loading />;
  if (!inst) return <Empty>No institution is linked to this account.</Empty>;

  const filteredOps = (ops.data ?? []).filter(
    (op: any) => (!ftype || op.employment_type === ftype) && (!fmode || op.work_mode === fmode)
  );

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Campus Hiring Opportunities"
        description={`Companies targeting ${inst.name} submit campus postings here for approval and cohort distribution.`}
      />

      {/* Filter and Tab Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-xs space-y-3">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex gap-1.5">
            {(["PENDING", "APPROVED", "REJECTED"] as const).map((k) => (
              <button
                key={k}
                onClick={() => setTab(k)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition ${
                  tab === k
                    ? "bg-blue-700 text-white shadow-xs"
                    : "text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                }`}
              >
                {k[0] + k.slice(1).toLowerCase()}
              </button>
            ))}
          </div>

          <div className="flex flex-wrap gap-2 text-xs items-center" data-testid="op-filters">
            <select
              className={inputCls}
              style={{ width: "13rem" }}
              aria-label="Filter by employment type"
              value={ftype}
              onChange={(e) => setFtype(e.target.value)}
            >
              <option value="">All Employment Types</option>
              {EMPLOYMENT_TYPES.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
            <select
              className={inputCls}
              style={{ width: "11rem" }}
              aria-label="Filter by work mode"
              value={fmode}
              onChange={(e) => setFmode(e.target.value)}
            >
              <option value="">All Work Modes</option>
              {WORK_MODES.map(([k, l]) => (
                <option key={k} value={k}>
                  {l}
                </option>
              ))}
            </select>
          </div>
        </div>
      </div>

      {ops.isLoading && <Loading label="Loading opportunities…" />}

      {!ops.isLoading && filteredOps.length === 0 && (
        <Card>
          <Empty>No {tab.toLowerCase()} campus opportunities found.</Empty>
        </Card>
      )}

      {structure.data && (
        <div className="space-y-3">
          {filteredOps.map((op: any) => (
            <OpportunityRow key={op.job_id} inst={inst} op={op} structure={structure.data} />
          ))}
        </div>
      )}
    </div>
  );
}
