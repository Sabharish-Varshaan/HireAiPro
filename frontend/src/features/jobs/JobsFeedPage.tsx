import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";
import { JobFacts } from "../../components/JobSummary";
import { EMPLOYMENT_TYPES, WORK_MODES } from "../../lib/posting";

const Chip = ({ on, onClick, children }: { on: boolean; onClick: () => void; children: string }) => (
  <button onClick={onClick} className={`text-xs px-3 py-1 rounded-full border ${on ? "bg-gray-900 text-white border-gray-900" : "border-gray-300 text-gray-700"}`}>{children}</button>
);

export default function JobsFeedPage() {
  const [type, setType] = useState("");
  const [mode, setMode] = useState("");
  const { data: jobs, isLoading, error } = useQuery({
    queryKey: ["jobs", "PUBLISHED", type, mode],
    queryFn: () => api.get("/jobs", { params: { status: "PUBLISHED", employment_type: type || undefined, work_mode: mode || undefined } }).then((r) => r.data),
  });

  return (
    <div className="max-w-3xl space-y-4">
      <h1 className="text-lg font-semibold text-gray-900">Open roles</h1>
      <div className="space-y-2" data-testid="job-filters">
        <div className="flex flex-wrap gap-2 items-center"><span className="text-xs text-gray-500 w-20">Type</span>
          <Chip on={!type} onClick={() => setType("")}>All</Chip>
          {EMPLOYMENT_TYPES.map(([k, l]) => <Chip key={k} on={type === k} onClick={() => setType(k)}>{l}</Chip>)}</div>
        <div className="flex flex-wrap gap-2 items-center"><span className="text-xs text-gray-500 w-20">Work mode</span>
          <Chip on={!mode} onClick={() => setMode("")}>All</Chip>
          {WORK_MODES.map(([k, l]) => <Chip key={k} on={mode === k} onClick={() => setMode(k)}>{l}</Chip>)}</div>
      </div>
      {isLoading && <p className="text-sm text-gray-500">Loading...</p>}
      {error && <p className="text-sm text-red-600">Could not load roles.</p>}
      {jobs?.length === 0 && <p className="text-sm text-gray-500">{type || mode ? "No roles match these filters." : "No published roles yet."}</p>}
      <div className="space-y-3">
        {jobs?.map((job: any) => (
          <Link key={job.id} to={`/student/jobs/${job.id}`} className="block bg-white border border-gray-200 rounded-lg p-4 hover:border-gray-300" data-testid="job-card">
            <p className="font-medium text-gray-900">{job.title}</p>
            <p className="text-sm text-gray-500 mb-1">{job.organization_name}</p>
            <JobFacts job={job} compact />
          </Link>
        ))}
      </div>
    </div>
  );
}
