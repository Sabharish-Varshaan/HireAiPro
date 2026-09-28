import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, Card, Empty, ErrorBox, Loading, Table, inputCls } from "../../components/ui";

const NEXT: Record<string, string[]> = {
  DRAFT: ["VALIDATED", "REJECTED"], VALIDATED: ["APPROVED", "REJECTED"], APPROVED: ["ACTIVE", "REJECTED"],
  ACTIVE: ["RETIRED"], REJECTED: ["DRAFT"], RETIRED: [],
};

function ImportResult({ r }: { r: any }) {
  if (!r) return null;
  return (
    <div className="text-xs text-gray-700 bg-gray-50 border border-gray-200 rounded p-2">
      Created {r.created} (validated {r.validated}, draft {r.draft}); duplicates skipped {r.duplicates.length}.
      {r.errors.length > 0 && <ul className="text-red-600 mt-1">{r.errors.map((e: any, i: number) => <li key={i}>row {e.row}: {e.error}</li>)}</ul>}
    </div>
  );
}

export default function QuestionBankPage({ organizationId, admin = false }: { organizationId?: string; admin?: boolean }) {
  const qc = useQueryClient();
  const [filters, setFilters] = useState({ status: "", source_type: "", q: "" });
  const [form, setForm] = useState({ question_text: "", question_type: "TECHNICAL", skill: "", difficulty: "medium",
    options: "", correct_option: "0", expected_concepts: "", criteria: "", test_cases: "" });
  const [paste, setPaste] = useState({ text: "", skill: "", question_type: "TECHNICAL" });
  const [result, setResult] = useState<any>(null);

  const params = { ...(organizationId ? { organization_id: organizationId } : {}),
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)) };
  const list = useQuery({ queryKey: ["questions", params], queryFn: () => api.get("/questions", { params }).then((r) => r.data) });
  const done = (r: any) => { setResult(r.data); qc.invalidateQueries({ queryKey: ["questions"] }); };
  const orgParams = organizationId ? { params: { organization_id: organizationId } } : {};

  const create = useMutation({
    onMutate: () => setResult(null),
    mutationFn: () => {
      const body: any = { question_text: form.question_text, question_type: form.question_type, skill: form.skill,
        difficulty: form.difficulty, organization_id: organizationId };
      if (form.question_type === "MCQ") { body.options = form.options.split("|").map((s) => s.trim()).filter(Boolean); body.correct_option = Number(form.correct_option); }
      if (form.question_type === "TECHNICAL") {
        if (form.expected_concepts) body.expected_concepts = form.expected_concepts.split("|").map((s) => s.trim());
        if (form.criteria) body.rubric = { criteria: form.criteria.split("|").map((s) => s.trim()) };
      }
      if (form.question_type === "CODING") body.test_cases = JSON.parse(form.test_cases || "[]");
      return api.post("/questions", body);
    },
    onSuccess: (r) => { done(r); setForm((f) => ({ ...f, question_text: "", options: "", expected_concepts: "", criteria: "", test_cases: "" })); },
  });
  const pasteImport = useMutation({ onMutate: () => setResult(null), mutationFn: () => api.post("/questions/import/paste", { ...paste, organization_id: organizationId }), onSuccess: (r) => { done(r); setPaste((p) => ({ ...p, text: "" })); } });
  const fileImport = useMutation({
    onMutate: () => setResult(null),
    mutationFn: (f: File) => { const fd = new FormData(); fd.append("file", f); return api.post("/questions/import/file", fd, orgParams); },
    onSuccess: done,
  });
  const transition = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.post(`/questions/${id}/transition`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["questions"] }),
  });
  const promote = useMutation({ mutationFn: (id: string) => api.post(`/questions/${id}/promote`), onSuccess: () => qc.invalidateQueries({ queryKey: ["questions"] }) });

  return (
    <div className="max-w-6xl space-y-5">
      <h1 className="text-lg font-semibold">{admin ? "Question review" : "Question bank"}</h1>
      {!admin && (
        <div className="grid md:grid-cols-2 gap-4">
          <Card title="Add a question">
            <textarea className={inputCls} rows={3} placeholder="Question text" value={form.question_text} onChange={(e) => setForm({ ...form, question_text: e.target.value })} />
            <div className="grid grid-cols-3 gap-2">
              <select className={inputCls} value={form.question_type} onChange={(e) => setForm({ ...form, question_type: e.target.value })}>
                <option>TECHNICAL</option><option>MCQ</option><option>CODING</option>
              </select>
              <input className={inputCls} placeholder="Skill (e.g. FastAPI)" value={form.skill} onChange={(e) => setForm({ ...form, skill: e.target.value })} />
              <select className={inputCls} value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
                <option>easy</option><option>medium</option><option>hard</option>
              </select>
            </div>
            {form.question_type === "MCQ" && (
              <div className="grid grid-cols-3 gap-2">
                <input className={`${inputCls} col-span-2`} placeholder="Options separated by |" value={form.options} onChange={(e) => setForm({ ...form, options: e.target.value })} />
                <input className={inputCls} type="number" min={0} placeholder="Correct index" value={form.correct_option} onChange={(e) => setForm({ ...form, correct_option: e.target.value })} />
              </div>
            )}
            {form.question_type === "TECHNICAL" && (
              <>
                <input className={inputCls} placeholder="Expected concepts separated by | (optional — AI fills if blank)" value={form.expected_concepts} onChange={(e) => setForm({ ...form, expected_concepts: e.target.value })} />
                <input className={inputCls} placeholder="Rubric criteria separated by | (optional)" value={form.criteria} onChange={(e) => setForm({ ...form, criteria: e.target.value })} />
              </>
            )}
            {form.question_type === "CODING" && (
              <textarea className={`${inputCls} font-mono text-xs`} rows={3} placeholder='[{"input": "[1, 2]", "expected_output": "3"}, …]' value={form.test_cases} onChange={(e) => setForm({ ...form, test_cases: e.target.value })} />
            )}
            <Button onClick={() => create.mutate()} disabled={create.isPending || !form.question_text || !form.skill}>{create.isPending ? "Validating…" : "Add"}</Button>
            <ErrorBox error={create.error} />
          </Card>
          <Card title="Import">
            <textarea className={inputCls} rows={4} placeholder="Paste questions, one per blank-line-separated block" value={paste.text} onChange={(e) => setPaste({ ...paste, text: e.target.value })} />
            <div className="grid grid-cols-2 gap-2">
              <input className={inputCls} placeholder="Skill for pasted questions" value={paste.skill} onChange={(e) => setPaste({ ...paste, skill: e.target.value })} />
              <Button variant="secondary" onClick={() => pasteImport.mutate()} disabled={pasteImport.isPending || !paste.text || !paste.skill}>Import pasted</Button>
            </div>
            <div className="text-sm flex items-center gap-2">
              <span className="text-gray-500">CSV or JSON file:</span>
              <input type="file" accept=".csv,.json" onChange={(e) => e.target.files?.[0] && fileImport.mutate(e.target.files[0])} />
            </div>
            <p className="text-xs text-gray-400">CSV columns: question_text, question_type, skill, difficulty, options, correct_option, expected_concepts, test_cases</p>
            <ErrorBox error={pasteImport.error || fileImport.error} />
          </Card>
        </div>
      )}
      <ImportResult r={result} />

      <Card title="Questions">
        <div className="grid grid-cols-3 gap-2">
          <select className={inputCls} value={filters.status} onChange={(e) => setFilters({ ...filters, status: e.target.value })}>
            <option value="">Any status</option>{Object.keys(NEXT).map((s) => <option key={s}>{s}</option>)}
          </select>
          <select className={inputCls} value={filters.source_type} onChange={(e) => setFilters({ ...filters, source_type: e.target.value })}>
            <option value="">Any origin</option><option>COMPANY_PRIVATE</option><option>PLATFORM</option><option>AI_GENERATED</option>
          </select>
          <input className={inputCls} placeholder="Search text" value={filters.q} onChange={(e) => setFilters({ ...filters, q: e.target.value })} />
        </div>
        {list.isLoading && <Loading />}
        <ErrorBox error={list.error || transition.error || promote.error} onRetry={list.refetch} />
        {list.data?.length === 0 && <Empty>No questions match.</Empty>}
        {list.data?.length > 0 && (
          <Table head={["Question", "Skill", "Type", "Origin", "Visibility", "Status", "Validation", "Actions"]}>
            {list.data.map((q: any) => (
              <tr key={q.id} className="align-top">
                <td className="py-2 pr-3 max-w-md">{q.question_text}
                  {(q.source_refs ?? []).length > 0 && <div className="text-xs text-gray-400">grounded on: {q.source_refs.map((r: any) => r.title).join(", ")}</div>}
                </td>
                <td className="pr-3">{q.skill_name}</td>
                <td className="pr-3"><Badge tone="gray">{q.question_type}</Badge></td>
                <td className="pr-3 text-xs">{q.source_type}</td>
                <td className="pr-3 text-xs">{q.visibility}</td>
                <td className="pr-3"><Badge>{q.status}</Badge></td>
                <td className="pr-3 text-xs text-gray-500">{q.validation_report ? (q.validation_report.ok ? "passed" : (q.validation_report.reasons ?? []).join("; ")) : "—"}</td>
                <td className="space-x-1 whitespace-nowrap">
                  {(NEXT[q.status] ?? []).map((s) => (
                    <button key={s} className="text-xs underline disabled:opacity-40" disabled={transition.isPending} onClick={() => transition.mutate({ id: q.id, status: s })}>{s.toLowerCase()}</button>
                  ))}
                  {admin && q.visibility !== "PLATFORM_PUBLIC" && ["APPROVED", "ACTIVE"].includes(q.status) && (
                    <button className="text-xs underline text-blue-700" onClick={() => promote.mutate(q.id)}>promote to platform</button>
                  )}
                </td>
              </tr>
            ))}
          </Table>
        )}
      </Card>
    </div>
  );
}
