import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client";

export default function CompanyJobsPage() {
  const qc = useQueryClient();
  const [orgName, setOrgName] = useState("");
  const [title, setTitle] = useState("");

  const { data: orgs } = useQuery({
    queryKey: ["orgs-mine"],
    queryFn: () => api.get("/organizations/mine").then((r) => r.data),
  });
  const org = orgs?.[0];

  const { data: jobs } = useQuery({
    queryKey: ["jobs-org", org?.id],
    queryFn: () => api.get("/jobs", { params: { organization_id: org.id } }).then((r) => r.data),
    enabled: !!org?.id,
  });

  const createOrg = useMutation({
    mutationFn: () => api.post("/organizations", { name: orgName }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["orgs-mine"] }),
  });

  const createJob = useMutation({
    mutationFn: () => api.post("/jobs", { title, description_raw: "" }, { params: { organization_id: org.id } }),
    onSuccess: () => {
      setTitle("");
      qc.invalidateQueries({ queryKey: ["jobs-org", org?.id] });
    },
  });

  if (!org) {
    return (
      <div className="max-w-sm space-y-3">
        <h1 className="text-lg font-semibold text-gray-900">Create your company</h1>
        <input
          className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="Company name"
          value={orgName}
          onChange={(e) => setOrgName(e.target.value)}
        />
        <button onClick={() => createOrg.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
          Create
        </button>
      </div>
    );
  }

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold text-gray-900">{org.name} — Jobs</h1>
      </div>
      <div className="flex gap-2">
        <input
          className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
          placeholder="New job title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
        <button onClick={() => createJob.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
          Create job
        </button>
      </div>
      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        {jobs && jobs.length === 0 && <p className="p-4 text-sm text-gray-500">No jobs yet. Create one above, then paste its job description.</p>}
        {jobs?.map((j: any) => (
          <Link key={j.id} to={`/company/jobs/${j.id}`} className="p-4 flex items-center justify-between text-sm hover:bg-gray-50">
            <span className="text-gray-800">{j.title}</span>
            <span className="text-xs px-2 py-1 rounded-full bg-gray-100 text-gray-600">{j.status}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
