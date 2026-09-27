import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";

export default function InstitutionDashboard() {
  const qc = useQueryClient();
  const [name, setName] = useState("");

  const { data: demand } = useQuery({
    queryKey: ["industry-demand"],
    queryFn: () => api.get("/institutions/analytics/industry-demand").then((r) => r.data),
  });

  const createInstitution = useMutation({
    mutationFn: () => api.post("/institutions", null, { params: { name } }),
    onSuccess: () => qc.invalidateQueries(),
  });

  return (
    <div className="max-w-3xl space-y-6">
      <h1 className="text-lg font-semibold text-gray-900">Institution analytics</h1>

      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-2">
        <h2 className="text-sm font-semibold text-gray-700">Register institution</h2>
        <div className="flex gap-2">
          <input
            className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="Institution name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <button onClick={() => createInstitution.mutate()} className="bg-gray-900 text-white text-sm px-4 py-2 rounded-md">
            Create
          </button>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg p-4">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Industry-wide skill demand (real-time, SQL-aggregated)</h2>
        <div className="space-y-2">
          {demand?.map((d: any) => (
            <div key={d.skill_id} className="flex items-center justify-between text-sm">
              <span className="text-gray-700">{d.skill_name}</span>
              <span className="text-xs text-gray-500">{d.demand_count} jobs · avg importance {d.avg_importance}</span>
            </div>
          ))}
          {(!demand || demand.length === 0) && (
            <p className="text-sm text-gray-500">No confirmed job requirements yet across the platform.</p>
          )}
        </div>
      </div>
    </div>
  );
}
