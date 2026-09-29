import { useQuery } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import { EMPLOYMENT_TYPES, WORK_MODES } from "../../lib/posting";
import {
  Badge,
  Card,
  Empty,
  PageHeader,
  SkeletonCard,
  inputCls,
} from "../../components/ui";

const Chip = ({
  on,
  onClick,
  children,
}: {
  on: boolean;
  onClick: () => void;
  children: string;
}) => (
  <button
    onClick={onClick}
    className={`text-xs px-3 py-1.5 rounded-full font-medium transition ${
      on
        ? "bg-blue-700 text-white shadow-sm"
        : "bg-white border border-gray-300 text-gray-700 hover:bg-gray-50"
    }`}
  >
    {children}
  </button>
);

export default function JobsFeedPage() {
  const [type, setType] = useState("");
  const [mode, setMode] = useState("");
  const [search, setSearch] = useState("");

  const { data: jobs, isLoading, error } = useQuery({
    queryKey: ["jobs", "PUBLISHED", type, mode],
    queryFn: () =>
      api
        .get("/jobs", {
          params: {
            status: "PUBLISHED",
            employment_type: type || undefined,
            work_mode: mode || undefined,
          },
        })
        .then((r) => r.data),
  });

  const { data: myApps } = useQuery({
    queryKey: ["applications-mine"],
    queryFn: () => api.get("/applications/mine").then((r) => r.data),
  });

  const appliedJobIds = useMemo(() => {
    return new Set((myApps ?? []).map((a: any) => a.job_id));
  }, [myApps]);

  const filteredJobs = useMemo(() => {
    if (!jobs) return [];
    if (!search.trim()) return jobs;
    const q = search.toLowerCase();
    return jobs.filter(
      (j: any) =>
        j.title?.toLowerCase().includes(q) ||
        j.organization_name?.toLowerCase().includes(q) ||
        j.location?.toLowerCase().includes(q)
    );
  }, [jobs, search]);

  return (
    <div className="max-w-4xl space-y-6">
      <PageHeader
        title="Explore Opportunities"
        description="Browse active roles, review skill requirements, and submit your verified application."
      />

      {/* Filter and Search Bar */}
      <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm space-y-3" data-testid="job-filters">
        <div className="flex gap-2">
          <input
            className={inputCls}
            placeholder="Search by role title, company, or city…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        <div className="space-y-2 pt-1 border-t border-gray-100">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-gray-500 w-24">Employment Type</span>
            <Chip on={!type} onClick={() => setType("")}>
              All
            </Chip>
            {EMPLOYMENT_TYPES.map(([k, l]) => (
              <Chip key={k} on={type === k} onClick={() => setType(k)}>
                {l}
              </Chip>
            ))}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-semibold text-gray-500 w-24">Work Mode</span>
            <Chip on={!mode} onClick={() => setMode("")}>
              All
            </Chip>
            {WORK_MODES.map(([k, l]) => (
              <Chip key={k} on={mode === k} onClick={() => setMode(k)}>
                {l}
              </Chip>
            ))}
          </div>
        </div>
      </div>

      <div className="flex items-center justify-between text-xs text-gray-500 px-1">
        <span>Showing {filteredJobs.length} available opportunities</span>
      </div>

      {isLoading && (
        <div className="space-y-3">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      )}

      {error && (
        <p className="text-sm text-red-600 bg-red-50 p-3 rounded-lg border border-red-200">
          Could not load roles. Please try again.
        </p>
      )}

      {!isLoading && filteredJobs.length === 0 && (
        <Card>
          <Empty>
            {type || mode || search
              ? "No roles match your current search and filter selections."
              : "No published roles available at this time."}
          </Empty>
        </Card>
      )}

      <div className="space-y-3">
        {filteredJobs.map((job: any) => {
          const alreadyApplied = appliedJobIds.has(job.id);
          return (
            <Link
              key={job.id}
              to={`/student/jobs/${job.id}`}
              className="group block bg-white border border-gray-200 rounded-xl p-5 hover:border-blue-400 hover:shadow-md transition duration-150"
              data-testid="job-card"
            >
              <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
                <div className="space-y-1.5 min-w-0">
                  <div className="flex items-center gap-2.5">
                    <h2 className="text-base font-semibold text-gray-900 group-hover:text-blue-700 transition">
                      {job.title}
                    </h2>
                    {alreadyApplied && (
                      <Badge tone="green">Applied</Badge>
                    )}
                  </div>
                  <p className="text-sm font-medium text-gray-600">{job.organization_name}</p>
                  <div className="pt-1">
                    <JobFacts job={job} compact />
                  </div>
                </div>
                <div className="flex items-center gap-2 shrink-0 self-end sm:self-center">
                  <span className="text-xs font-semibold text-blue-700 group-hover:underline">
                    View Details →
                  </span>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </div>
  );
}
