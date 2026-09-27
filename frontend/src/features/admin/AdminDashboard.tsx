import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

export default function AdminDashboard() {
  const { data: aiRuns } = useQuery({ queryKey: ["ai-runs"], queryFn: () => api.get("/admin/ai-runs").then((r) => r.data) });
  const { data: agentRuns } = useQuery({ queryKey: ["agent-runs"], queryFn: () => api.get("/admin/agent-runs").then((r) => r.data) });
  const { data: skills } = useQuery({ queryKey: ["admin-skills"], queryFn: () => api.get("/admin/skills").then((r) => r.data) });
  const { data: aiQuestions } = useQuery({ queryKey: ["ai-questions"], queryFn: () => api.get("/admin/questions/ai-generated").then((r) => r.data) });

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-lg font-semibold text-gray-900">Platform admin</h1>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-gray-500">Skills in taxonomy</p>
          <p className="text-2xl font-semibold">{skills?.length ?? "—"}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-gray-500">AI runs logged</p>
          <p className="text-2xl font-semibold">{aiRuns?.length ?? "—"}</p>
        </div>
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-gray-500">AI-generated questions</p>
          <p className="text-2xl font-semibold">{aiQuestions?.length ?? "—"}</p>
        </div>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        <h2 className="text-sm font-semibold text-gray-700 p-4 pb-2">Recent AI runs</h2>
        {aiRuns?.slice(0, 20).map((r: any) => (
          <div key={r.id} className="p-3 flex items-center justify-between text-xs">
            <span>{r.task_type}</span>
            <span>{r.model}</span>
            <span className={r.status === "FAILED" ? "text-red-600" : "text-gray-500"}>{r.status}</span>
          </div>
        ))}
      </div>

      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        <h2 className="text-sm font-semibold text-gray-700 p-4 pb-2">Agent runs</h2>
        {agentRuns?.slice(0, 20).map((r: any) => (
          <div key={r.id} className="p-3 flex items-center justify-between text-xs">
            <span>{r.agent_type}</span>
            <span>{r.task}</span>
            <span className={r.status === "FAILED" ? "text-red-600" : "text-gray-500"}>{r.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
