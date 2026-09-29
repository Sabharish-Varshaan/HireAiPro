import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import { PostingFormFields } from "../../components/PostingFormFields";
import {
  Badge,
  Button,
  Card,
  Empty,
  ErrorBox,
  MetricCard,
  Modal,
  PageHeader,
  SkeletonCard,
  inputCls,
} from "../../components/ui";
import { emptyPosting, problems, toPayload, type PostingForm } from "../../lib/posting";

export default function CompanyJobsPage() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [orgName, setOrgName] = useState("");
  const [creating, setCreating] = useState(false);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [f, setF] = useState<PostingForm>(emptyPosting());

  const { data: orgs, isLoading: orgsLoading } = useQuery({
    queryKey: ["orgs-mine"],
    queryFn: () => api.get("/organizations/mine").then((r) => r.data),
  });
  const org = orgs?.[0];

  const { data: jobs, isLoading: jobsLoading } = useQuery({
    queryKey: ["jobs-org", org?.id],
    enabled: !!org?.id,
    queryFn: () => api.get("/jobs", { params: { organization_id: org.id } }).then((r) => r.data),
  });

  const createOrg = useMutation({
    mutationFn: () => api.post("/organizations", { name: orgName }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orgs-mine"] }),
  });

  const createJob = useMutation({
    mutationFn: () =>
      api
        .post("/jobs", { ...toPayload(f, true), description_raw: "" }, { params: { organization_id: org.id } })
        .then((r) => r.data),
    onSuccess: (j) => {
      setCreating(false);
      setF(emptyPosting());
      qc.invalidateQueries({ queryKey: ["jobs-org", org?.id] });
      navigate(`/company/jobs/${j.id}`);
    },
  });

  const filteredJobs = useMemo(() => {
    if (!jobs) return [];
    return jobs.filter((j: any) => {
      const matchSearch =
        !search.trim() ||
        j.title?.toLowerCase().includes(search.toLowerCase()) ||
        j.location?.toLowerCase().includes(search.toLowerCase());
      const matchStatus =
        statusFilter === "ALL" ||
        (statusFilter === "PUBLISHED" && j.status === "PUBLISHED") ||
        (statusFilter === "DRAFT" && ["DRAFT", "SKILLS_EXTRACTED", "REQUIREMENTS_CONFIRMED", "ASSESSMENT_READY"].includes(j.status)) ||
        (statusFilter === "CLOSED" && j.status === "CLOSED");
      return matchSearch && matchStatus;
    });
  }, [jobs, search, statusFilter]);

  if (orgsLoading) {
    return (
      <div className="max-w-6xl space-y-6">
        <SkeletonCard />
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      </div>
    );
  }

  if (!org) {
    return (
      <div className="max-w-md mx-auto mt-12 bg-white border border-gray-200 rounded-xl p-6 shadow-sm space-y-4">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Set up your company</h1>
          <p className="text-sm text-gray-500 mt-1">
            Create your company workspace to publish hiring opportunities and review candidates.
          </p>
        </div>
        <div className="space-y-2">
          <label className="text-xs font-medium text-gray-700">Company Name</label>
          <input
            className={inputCls}
            placeholder="e.g. Acme Technologies"
            value={orgName}
            onChange={(e) => setOrgName(e.target.value)}
          />
        </div>
        <Button
          onClick={() => createOrg.mutate()}
          disabled={!orgName.trim() || createOrg.isPending}
        >
          {createOrg.isPending ? "Creating…" : "Create company"}
        </Button>
        <ErrorBox error={createOrg.error} />
      </div>
    );
  }

  const errs = problems(f);

  const totalCount = jobs?.length ?? 0;
  const publishedCount = jobs?.filter((j: any) => j.status === "PUBLISHED").length ?? 0;
  const inReviewCount =
    jobs?.filter((j: any) =>
      ["DRAFT", "SKILLS_EXTRACTED", "REQUIREMENTS_CONFIRMED", "ASSESSMENT_READY"].includes(j.status)
    ).length ?? 0;

  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={org.name}
        description="Manage your open roles, requirements, assessments, and candidate pipeline."
        actions={
          <Button
            onClick={() => setCreating(true)}
            icon={
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
              </svg>
            }
          >
            New job posting
          </Button>
        }
      />

      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <MetricCard label="Total roles" value={totalCount} tone="default" />
        <MetricCard label="Published & active" value={publishedCount} tone="success" />
        <MetricCard label="Drafts & in setup" value={inReviewCount} tone="warning" />
      </div>

      <div className="flex flex-col sm:flex-row gap-3 items-stretch sm:items-center justify-between">
        <div className="relative flex-1 max-w-sm">
          <input
            className={inputCls}
            placeholder="Search roles by title or location…"
            aria-label="Search roles by title or location"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <div className="flex gap-1.5 bg-gray-100 p-1 rounded-lg self-start">
          {[
            { id: "ALL", label: `All (${totalCount})` },
            { id: "PUBLISHED", label: `Published (${publishedCount})` },
            { id: "DRAFT", label: `Drafts (${inReviewCount})` },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id)}
              className={`text-xs px-3 py-1.5 rounded-md font-medium transition ${
                statusFilter === tab.id
                  ? "bg-white text-gray-900 shadow-sm"
                  : "text-gray-600 hover:text-gray-900"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {jobsLoading ? (
        <div className="space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : filteredJobs.length === 0 ? (
        <Card>
          <Empty
            action={
              !search && statusFilter === "ALL" ? (
                <Button onClick={() => setCreating(true)}>Create your first role</Button>
              ) : null
            }
          >
            {!search && statusFilter === "ALL"
              ? "No job postings yet. Create your first role to start hiring."
              : "No roles match your current search and filters."}
          </Empty>
        </Card>
      ) : (
        <div className="grid gap-3">
          {filteredJobs.map((j: any) => (
            <Link
              key={j.id}
              to={`/company/jobs/${j.id}`}
              className="group block bg-white border border-gray-200 rounded-xl p-5 hover:border-blue-400 hover:shadow-md transition duration-150"
            >
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2">
                    <h2 className="text-base font-semibold text-gray-900 group-hover:text-blue-700 transition">
                      {j.title}
                    </h2>
                  </div>
                  <JobFacts job={j} compact />
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <Badge>{j.status}</Badge>
                  <svg
                    className="w-5 h-5 text-gray-400 group-hover:text-blue-600 group-hover:translate-x-0.5 transition"
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                    strokeWidth={2}
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
                  </svg>
                </div>
              </div>
            </Link>
          ))}
        </div>
      )}

      <Modal
        open={creating}
        onClose={() => {
          setCreating(false);
          setF(emptyPosting());
        }}
        title="Create new job posting"
      >
        <div className="space-y-4">
          <p className="text-xs text-gray-500">
            Start by entering the role details. Next, you will paste the job description, review extracted skills, and build the assessment.
          </p>
          <PostingFormFields f={f} set={(p) => setF((x) => ({ ...x, ...p }))} showTitle />
          <div className="flex justify-end gap-2 pt-2 border-t border-gray-100">
            <Button
              variant="secondary"
              onClick={() => {
                setCreating(false);
                setF(emptyPosting());
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => createJob.mutate()}
              disabled={!f.title.trim() || errs.length > 0 || createJob.isPending}
            >
              {createJob.isPending ? "Creating…" : "Create & continue"}
            </Button>
          </div>
          <ErrorBox error={createJob.error} />
        </div>
      </Modal>
    </div>
  );
}
