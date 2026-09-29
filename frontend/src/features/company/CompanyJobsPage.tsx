import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import { PostingFormFields } from "../../components/PostingFormFields";
import { Badge, Button, Card, ErrorBox } from "../../components/ui";
import { emptyPosting, problems, toPayload, type PostingForm } from "../../lib/posting";

const STATUS_LABEL: Record<string, string> = {
  DRAFT: "Draft", SKILLS_EXTRACTED: "Requirements to review", REQUIREMENTS_CONFIRMED: "Requirements confirmed", ASSESSMENT_READY: "Assessment ready",
  PUBLISHED: "Published", CLOSED: "Closed",
};

export default function CompanyJobsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [creating, setCreating] = useState(false);
  const [f, setF] = useState<PostingForm>(emptyPosting());

  const { data: orgs } = useQuery({ queryKey: ["orgs-mine"], queryFn: () => api.get("/organizations/mine").then((r) => r.data) });
  const org = orgs?.[0];
  const { data: jobs } = useQuery({
    queryKey: ["jobs-org", org?.id], enabled: !!org?.id,
    queryFn: () => api.get("/jobs", { params: { organization_id: org.id } }).then((r) => r.data),
  });
  const createOrg = useMutation({ mutationFn: () => api.post("/organizations", { name: orgName }), onSuccess: () => qc.invalidateQueries({ queryKey: ["orgs-mine"] }) });
  const createJob = useMutation({
    mutationFn: () => api.post("/jobs", { ...toPayload(f, true), description_raw: "" }, { params: { organization_id: org.id } }).then((r) => r.data),
    onSuccess: (j) => { setCreating(false); setF(emptyPosting()); qc.invalidateQueries({ queryKey: ["jobs-org", org?.id] }); navigate(`/company/jobs/${j.id}`); },
  });

  if (!org) {
    return (
      <div className="max-w-sm space-y-3">
        <h1 className="text-lg font-semibold text-gray-900">Create your company</h1>
        <input className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm" placeholder="Company name" value={orgName} onChange={(e) => setOrgName(e.target.value)} />
        <button onClick={() => createOrg.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">Create</button>
      </div>
    );
  }
  const errs = problems(f);
  return (
    <div className="max-w-3xl space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">{org.name} — Jobs</h1>
        {!creating && <Button onClick={() => setCreating(true)}>New job posting</Button>}
      </div>
      {creating && (
        <Card title="New job posting">
          <PostingFormFields f={f} set={(p) => setF((x) => ({ ...x, ...p }))} showTitle />
          <p className="text-xs text-gray-500">Next: paste the job description, confirm the requirements, then build the assessment. Employment type, work mode and location are required before publishing.</p>
          <div className="flex gap-2">
            <Button onClick={() => createJob.mutate()} disabled={!f.title.trim() || errs.length > 0 || createJob.isPending}>{createJob.isPending ? "Creating…" : "Create job"}</Button>
            <Button variant="secondary" onClick={() => { setCreating(false); setF(emptyPosting()); }}>Cancel</Button>
          </div>
          <ErrorBox error={createJob.error} />
        </Card>
      )}
      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        {jobs && jobs.length === 0 && <p className="p-4 text-sm text-gray-500">No jobs yet. Create a job posting above, then paste its job description.</p>}
        {jobs?.map((j: any) => (
          <Link key={j.id} to={`/company/jobs/${j.id}`} className="p-4 flex items-start justify-between gap-3 text-sm hover:bg-gray-50">
            <div><p className="text-gray-900 font-medium">{j.title}</p><JobFacts job={j} compact /></div>
            <Badge>{STATUS_LABEL[j.status] ?? j.status}</Badge>
          </Link>
        ))}
      </div>
    </div>
  );
}
