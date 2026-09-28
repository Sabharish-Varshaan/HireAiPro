import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";

export default function AdminDashboard() {
  const { data: aiRuns } = useQuery({ queryKey: ["ai-runs"], queryFn: () => api.get("/admin/ai-runs").then((r) => r.data) });
  const { data: agentRuns } = useQuery({ queryKey: ["agent-runs"], queryFn: () => api.get("/admin/agent-runs").then((r) => r.data) });
  const { data: skills } = useQuery({ queryKey: ["admin-skills"], queryFn: () => api.get("/admin/skills").then((r) => r.data) });
  const { data: aiQuestions } = useQuery({ queryKey: ["ai-questions"], queryFn: () => api.get("/questions", { params: { source_type: "AI_GENERATED" } }).then((r) => r.data) });
  const { data: usage } = useQuery({ queryKey: ["ai-usage"], queryFn: () => api.get("/admin/ai/usage").then((r) => r.data) });
  const { data: providers } = useQuery({ queryKey: ["ai-providers"], queryFn: () => api.get("/admin/ai/providers").then((r) => r.data) });

  return (
    <div className="max-w-4xl space-y-6">
      <h1 className="text-lg font-semibold text-gray-900">Platform admin</h1>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div className="bg-white border border-gray-200 rounded-lg p-4">
          <p className="text-gray-500">Skills in taxonomy</p>
          <p className="text-2xl font-semibold">{skills?.total ?? "—"}</p>
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

      <div className="bg-white border border-gray-200 rounded-lg p-4 space-y-3">
        <div className="flex items-baseline justify-between">
          <h2 className="text-sm font-semibold text-gray-700">AI usage & cost</h2>
          <span className="text-xs text-gray-500">{usage?.label}</span>
        </div>
        <div className="grid grid-cols-4 gap-3 text-sm">
          <div><p className="text-gray-500 text-xs">OpenAI today</p><p className="font-semibold">${usage?.openai_spend_today_usd?.toFixed(4) ?? "—"}</p></div>
          <div><p className="text-gray-500 text-xs">OpenAI last 10 days</p><p className="font-semibold">${usage?.openai_spend_10d_usd?.toFixed(4) ?? "—"}</p></div>
          <div><p className="text-gray-500 text-xs">Daily soft / hard cap</p><p className="font-semibold">${providers?.budget?.soft_limit_usd} / ${providers?.budget?.hard_limit_usd}</p></div>
          <div><p className="text-gray-500 text-xs">Budget state</p><p className="font-semibold">{providers?.budget?.state ?? "—"}</p></div>
        </div>
        <div className="flex gap-4 text-xs">
          {providers && (["groq", "openai", "ollama"] as const).map((k) => (
            <span key={k} className={providers[k].healthy ? "text-green-700" : "text-red-600"}>
              {k}: {providers[k].configured ? (providers[k].healthy ? "healthy" : "unreachable") : "not configured"}
            </span>
          ))}
        </div>
        <table className="w-full text-xs">
          <thead className="text-gray-500 text-left"><tr><th>Provider</th><th>Model</th><th>Requests</th><th>Failures</th><th>Fallbacks</th><th>Avg latency</th><th>Tokens in/out</th><th>Cost</th></tr></thead>
          <tbody>
            {(usage?.by_model ?? []).map((m: any) => (
              <tr key={m.provider + m.model} className="border-t border-gray-100">
                <td>{m.provider}</td><td>{m.model}</td><td>{m.requests}</td><td>{m.failures}</td><td>{m.fallbacks}</td>
                <td>{m.avg_latency_ms ? `${m.avg_latency_ms} ms` : "—"}</td><td>{m.input_tokens}/{m.output_tokens}</td><td>${m.estimated_cost_usd.toFixed(5)}</td>
              </tr>
            ))}
            {usage && usage.by_model.length === 0 && <tr><td colSpan={8} className="text-gray-500 py-2">No AI calls recorded yet.</td></tr>}
          </tbody>
        </table>
      </div>

      <div className="bg-white border border-gray-200 rounded-lg divide-y">
        <h2 className="text-sm font-semibold text-gray-700 p-4 pb-2">Recent AI runs</h2>
        {aiRuns?.slice(0, 20).map((r: any) => (
          <div key={r.id} className="p-3 flex items-center justify-between text-xs">
            <span>{r.task_type}</span>
            <span>{r.provider}:{r.model}</span>
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
