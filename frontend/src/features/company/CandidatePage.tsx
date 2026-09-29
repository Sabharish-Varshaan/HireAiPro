import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "react-router-dom";
import { api } from "../../api/client";
import { ProctoringPanel } from "../proctoring/ProctoringPanel";
import { RoundTimeline, StageResultCard, StageTimeline } from "./CandidateStages";
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
  humanize,
} from "../../components/ui";

export function MatchExplanation({ match }: { match: any }) {
  const w = match.weights ?? {};
  const parts = [
    ["Required skill fit", match.required_skill_fit, w.required],
    ["Preferred skill fit", match.preferred_skill_fit, w.preferred],
    ["Evidence confidence", match.evidence_confidence, w.evidence_confidence],
    ["Semantic profile relevance", match.semantic_relevance, w.semantic_relevance],
  ] as const;
  const list = (title: string, items: any[], tone: string) => (
    <div className="space-y-1">
      <p className="text-xs font-semibold text-gray-700">
        {title} ({items?.length ?? 0})
      </p>
      <div className="flex flex-wrap gap-1.5">
        {(items ?? []).map((s) => (
          <Badge key={s.skill_id} tone={tone}>{`${s.skill_name} · ${pct(s.fit)} fit`}</Badge>
        ))}
        {(items ?? []).length === 0 && <span className="text-xs text-gray-400">None identified</span>}
      </div>
    </div>
  );
  return (
    <div className="space-y-4">
      <div className="flex items-baseline gap-4 p-4 bg-gray-50 rounded-lg border border-gray-100">
        <div>
          <span className="text-xs text-gray-500 uppercase tracking-wider font-semibold block">
            Overall Match Score
          </span>
          <span className="text-3xl font-bold text-gray-900 tabular-nums">
            {pct(match.match_score, 1)}
          </span>
        </div>
      </div>
      <Table head={["Fit Component", "Score", "Weight", "Weighted Impact"]}>
        {parts.map(([label, v, wt]) => (
          <tr key={label} className="hover:bg-gray-50/50">
            <td className="py-2 pr-3 font-medium text-gray-900">{label}</td>
            <td className="pr-3 text-xs">{pct(v, 1)}</td>
            <td className="pr-3 text-xs text-gray-500">{wt != null ? pct(wt) : "—"}</td>
            <td className="text-xs font-semibold text-gray-900">
              {wt != null ? pct((v as number) * (wt as number), 1) : "—"}
            </td>
          </tr>
        ))}
      </Table>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
        {list("Strong Competencies", match.strong_skills, "green")}
        {list("Partial Competencies", match.partial_skills, "amber")}
        {list("Missing Competencies", match.missing_skills, "red")}
      </div>
    </div>
  );
}

const DECISIONS: Record<string, string[]> = {
  APPLIED: ["ASSESSMENT_PENDING", "REJECTED"],
  ASSESSMENT_PENDING: ["REJECTED"],
  ASSESSMENT_COMPLETED: ["UNDER_REVIEW", "REJECTED"],
  INTERVIEW_PENDING: ["REJECTED"],
  INTERVIEW_COMPLETED: ["UNDER_REVIEW", "REJECTED"],
  UNDER_REVIEW: ["SHORTLISTED", "REJECTED"],
  SHORTLISTED: ["OFFER", "REJECTED"],
};

const DECISION_LABEL: Record<string, string> = {
  SHORTLISTED: "Shortlist Candidate",
  REJECTED: "Reject Candidate",
  OFFER: "Extend Offer",
  UNDER_REVIEW: "Move to Review",
  ASSESSMENT_PENDING: "Send Assessment",
};

export default function CandidatePage() {
  const { applicationId } = useParams();
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [activeTab, setActiveTab] = useState<string>("overview");

  const app = useQuery({
    queryKey: ["application", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}`).then((r) => r.data),
  });
  const history = useQuery({
    queryKey: ["history", applicationId],
    queryFn: () => api.get(`/applications/${applicationId}/history`).then((r) => r.data),
  });
  const match = useQuery({
    queryKey: ["match", applicationId],
    retry: false,
    queryFn: () => api.get(`/matching/applications/${applicationId}`).then((r) => r.data),
  });
  const sid = app.data?.student_id;
  const skills = useQuery({
    queryKey: ["cand-skills", sid],
    enabled: !!sid,
    queryFn: () => api.get(`/evidence/students/${sid}/skills`).then((r) => r.data),
  });
  const evidence = useQuery({
    queryKey: ["cand-evidence", sid],
    enabled: !!sid,
    queryFn: () => api.get(`/evidence/students/${sid}/evidence`).then((r) => r.data),
  });
  const pipeline = useQuery({
    queryKey: ["cand-pipeline", applicationId],
    queryFn: () => api.get(`/hiring-pipeline/applications/${applicationId}`).then((r) => r.data),
  });

  const compute = useMutation({
    mutationFn: () => api.post(`/matching/applications/${applicationId}/compute`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["match", applicationId] }),
  });
  const decide = useMutation({
    mutationFn: (status: string) =>
      api.put(`/applications/${applicationId}/status`, { status, note: note || null }),
    onSuccess: () => {
      setNote("");
      qc.invalidateQueries({ queryKey: ["application", applicationId] });
      qc.invalidateQueries({ queryKey: ["history", applicationId] });
    },
  });

  if (app.isLoading) return <Loading />;
  if (app.error) return <ErrorBox error={app.error} onRetry={app.refetch} />;
  const a = app.data;
  const matchMissing = (match.error as any)?.response?.status === 404;

  const availableDecisions = DECISIONS[a.status] ?? [];
  const stages: any[] = pipeline.data?.stages ?? [];
  const activeStage = activeTab.startsWith("stage:") ? stages.find((s) => `stage:${s.stage_type}` === activeTab) : null;

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        back={{ label: a.job_title, href: `/company/jobs/${a.job_id}` }}
        title={a.student_name}
        description={`Application for ${a.job_title}`}
        actions={
          <div className="flex items-center gap-2">
            <Badge>{a.status}</Badge>
            {match.data?.match_score != null && (
              <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-50 text-emerald-800 border border-emerald-200">
                {pct(match.data.match_score, 1)} Match
              </span>
            )}
          </div>
        }
      />

      <Card title="Hiring stages" description="Where this candidate is in this role's hiring process.">
        <StageTimeline stages={stages} applicationStatus={a.status} />
      </Card>

      <Tabs
        tabs={[
          { id: "overview", label: "Overview & Fit" },
          ...stages.map((s: any) => ({ id: `stage:${s.stage_type}`, label: s.label })),
          { id: "evidence", label: `Evidence (${evidence.data?.length ?? 0})` },
          { id: "proctoring", label: "Proctoring" },
          { id: "decision", label: "Status & Decision" },
        ]}
        current={activeTab}
        onChange={(t) => setActiveTab(t)}
      />

      {activeTab === "overview" && (
        <div className="space-y-5">
          <Card
            title="Candidate Match Breakdown"
            description="Algorithmic match comparison against confirmed role requirements."
            actions={
              <Button
                variant="secondary"
                size="sm"
                onClick={() => compute.mutate()}
                disabled={compute.isPending}
              >
                {compute.isPending ? "Calculating…" : "Recalculate fit"}
              </Button>
            }
          >
            {match.isLoading && <Loading />}
            {matchMissing && (
              <Empty>
                Fit score is calculated automatically when the interview completes, or you can calculate now.
              </Empty>
            )}
            {match.data && <MatchExplanation match={match.data} />}
            <ErrorBox error={compute.error} />
          </Card>

          <Card
            title="Verified Skill Profile"
            description="Demonstrated competency levels aggregated from assessments and interviews."
          >
            {(skills.data ?? []).length === 0 ? (
              <Empty>No verified skills demonstrated yet.</Empty>
            ) : (
              <Table head={["Competency", "Demonstrated Level", "Confidence", "Evidence Count"]}>
                {skills.data.map((s: any) => (
                  <tr key={s.skill_id} className="hover:bg-gray-50/50">
                    <td className="py-2 pr-3 font-medium text-gray-900">{s.skill_name}</td>
                    <td className="pr-3 text-xs font-semibold">{pct(s.estimated_level)}</td>
                    <td className="pr-3 text-xs text-gray-600">{pct(s.confidence)}</td>
                    <td className="pr-3 text-xs text-gray-500">{s.evidence_count} evidence records</td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      )}

      {activeStage && (
        <div className="space-y-5">
          <StageResultCard applicationId={applicationId!} stage={activeStage} />
        </div>
      )}

      {activeTab === "evidence" && (
        <div className="space-y-5">
          <Card
            title="Demonstrated Evidence Log"
            description="Detailed evidence entries gathered throughout the evaluation process."
          >
            {(evidence.data ?? []).length === 0 ? (
              <Empty>No evidence recorded yet.</Empty>
            ) : (
              <Table head={["Skill", "Source Type", "Score", "Confidence", "Difficulty", "Recorded At"]}>
                {evidence.data.map((e: any) => (
                  <tr key={e.id} className="hover:bg-gray-50/50">
                    <td className="py-2.5 pr-3 font-medium text-gray-900">{e.skill_name}</td>
                    <td className="pr-3">
                      <Badge tone={e.source_type === "RESUME_CLAIM" ? "gray" : "blue"}>{e.source_type}</Badge>
                    </td>
                    <td className="pr-3 text-xs font-semibold">{pct(e.normalized_score)}</td>
                    <td className="pr-3 text-xs text-gray-500">{pct(e.confidence)}</td>
                    <td className="pr-3 text-xs text-gray-500">{e.difficulty ?? "—"}</td>
                    <td className="text-xs text-gray-500">{new Date(e.created_at).toLocaleDateString()}</td>
                  </tr>
                ))}
              </Table>
            )}
          </Card>
        </div>
      )}

      {activeTab === "proctoring" && (
        <div className="space-y-5">
          <Card title="Proctoring & Integrity Timeline" description="Objective browser and hardware events captured during sessions.">
            <ProctoringPanel applicationId={applicationId!} />
          </Card>
        </div>
      )}

      {activeTab === "decision" && (
        <div className="space-y-5">
          <Card
            title="Round results"
            description="Each round's score against its qualification requirement. The automatic result is never edited; a recruiter override is recorded beside it."
          >
            <RoundTimeline
              applicationId={applicationId!}
              stages={stages}
              onChanged={() => ["cand-pipeline", "application", "history"].forEach((k) => qc.invalidateQueries({ queryKey: [k] }))}
            />
          </Card>
          <Card
            title="Hiring Decision & Status"
            description="Update the candidate status and record internal reviewer notes."
          >
            <div className="space-y-3">
              <div className="flex flex-col sm:flex-row gap-2">
                <input
                  className={inputCls}
                  placeholder="Decision note (optional, e.g. Strong system design, proceed to final round)"
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
                <div className="flex gap-2 shrink-0">
                  {availableDecisions.map((s) => (
                    <Button
                      key={s}
                      variant={s === "REJECTED" ? "danger" : "primary"}
                      onClick={() => decide.mutate(s)}
                      disabled={decide.isPending}
                    >
                      {DECISION_LABEL[s] ?? s.replaceAll("_", " ")}
                    </Button>
                  ))}
                </div>
              </div>
              {availableDecisions.length === 0 && (
                <p className="text-xs text-gray-500">
                  No recruiter status transition is available in the current status ({humanize(a.status).toLowerCase()}).
                </p>
              )}
              <ErrorBox error={decide.error} />
            </div>

            <div className="pt-4 border-t border-gray-100">
              <h3 className="text-xs font-semibold text-gray-700 mb-2">Status Transition History</h3>
              <ol className="text-xs space-y-2">
                {(history.data ?? []).map((h: any, i: number) => (
                  <li key={i} className="flex items-start gap-2 text-gray-600">
                    <span className="font-mono text-gray-400 shrink-0">
                      {new Date(h.at).toLocaleDateString()} {new Date(h.at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </span>
                    <span>
                      {h.from ? <Badge tone="gray">{h.from}</Badge> : <span>Initial</span>} →{" "}
                      <Badge>{h.to}</Badge>
                      {h.by_system && <span className="text-gray-400 ml-1">(automated)</span>}
                      {h.note && <span className="text-gray-700 ml-1">· “{h.note}”</span>}
                    </span>
                  </li>
                ))}
              </ol>
            </div>
          </Card>
        </div>
      )}
    </div>
  );
}
