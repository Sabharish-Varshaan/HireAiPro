import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
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
  humanize,
  questionTypeLabel,
} from "../../components/ui";
import { APTITUDE_CATEGORIES, HR_CATEGORY_LABEL } from "../../lib/pipeline";

const NEXT: Record<string, string[]> = {
  DRAFT: ["VALIDATED", "REJECTED"],
  VALIDATED: ["APPROVED", "REJECTED"],
  APPROVED: ["ACTIVE", "REJECTED"],
  ACTIVE: ["RETIRED"],
  REJECTED: ["DRAFT"],
  RETIRED: [],
};

function ImportResult({ r }: { r: any }) {
  if (!r) return null;
  return (
    <div className="text-xs text-gray-700 bg-emerald-50 border border-emerald-200 rounded-lg p-3">
      <span className="font-semibold text-emerald-800">Import successful: </span>
      Created {r.created} (validated {r.validated}, draft {r.draft}); duplicates skipped {r.duplicates.length}.
      {r.errors?.length > 0 && (
        <ul className="text-red-600 mt-1 list-disc ml-4">
          {r.errors.map((e: any, i: number) => (
            <li key={i}>
              Row {e.row}: {e.error}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const DOMAIN_LABEL: Record<string, string> = { TECHNICAL: "Technical", APTITUDE: "Aptitude", CODING: "Coding", TECHNICAL_INTERVIEW: "Technical interview", HR_INTERVIEW: "HR interview" };
const DOMAIN_OPTIONS: [string, string][] = [
  ["TECHNICAL", "Technical assessment"],
  ["APTITUDE", "Aptitude assessment"],
  ["CODING", "Coding assessment"],
  ["TECHNICAL_INTERVIEW", "Technical interview"],
  ["HR_INTERVIEW", "HR interview"],
];

export default function QuestionBankPage({
  organizationId,
  admin = false,
}: {
  organizationId?: string;
  admin?: boolean;
}) {
  const qc = useQueryClient();
  const [activeTab, setActiveTab] = useState<"browse" | "add" | "import">("browse");
  const [filters, setFilters] = useState({ status: "", source_type: "", q: "", domain: "" });
  const [form, setForm] = useState({
    question_text: "",
    question_type: "TECHNICAL",
    domain: "TECHNICAL",
    category: "",
    skill: "",
    difficulty: "medium",
    options: "",
    correct_option: "0",
    expected_concepts: "",
    criteria: "",
    test_cases: "",
  });
  const [paste, setPaste] = useState({ text: "", skill: "", question_type: "TECHNICAL" });
  const [result, setResult] = useState<any>(null);

  const params = {
    ...(organizationId ? { organization_id: organizationId } : {}),
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)),
  };
  const list = useQuery({
    queryKey: ["questions", params],
    queryFn: () => api.get("/questions", { params }).then((r) => r.data),
  });
  const done = (r: any) => {
    setResult(r.data);
    qc.invalidateQueries({ queryKey: ["questions"] });
  };
  const orgParams = organizationId ? { params: { organization_id: organizationId } } : {};

  const create = useMutation({
    onMutate: () => setResult(null),
    mutationFn: () => {
      const domain = form.domain;
      const body: any = {
        question_text: form.question_text,
        question_type: domain === "APTITUDE" ? "MCQ" : domain === "CODING" ? "CODING" : domain === "HR_INTERVIEW" || domain === "TECHNICAL_INTERVIEW" ? "TECHNICAL" : form.question_type,
        difficulty: form.difficulty,
        organization_id: organizationId,
        domain: domain === "CODING" ? "TECHNICAL" : domain,
      };
      if (domain !== "APTITUDE" && domain !== "HR_INTERVIEW") body.skill = form.skill;
      if (domain === "APTITUDE" || domain === "HR_INTERVIEW") body.category = form.category;
      if (body.question_type === "MCQ") {
        body.options = form.options.split("|").map((s) => s.trim()).filter(Boolean);
        body.correct_option = Number(form.correct_option);
      }
      if (body.question_type === "TECHNICAL" && domain !== "HR_INTERVIEW") {
        if (form.expected_concepts)
          body.expected_concepts = form.expected_concepts.split("|").map((s) => s.trim());
        if (form.criteria) body.rubric = { criteria: form.criteria.split("|").map((s) => s.trim()) };
      }
      if (body.question_type === "CODING") body.test_cases = JSON.parse(form.test_cases || "[]");
      return api.post("/questions", body);
    },
    onSuccess: (r) => {
      done(r);
      setForm((f) => ({
        ...f,
        question_text: "",
        options: "",
        expected_concepts: "",
        criteria: "",
        test_cases: "",
      }));
      setActiveTab("browse");
    },
  });
  const pasteImport = useMutation({
    onMutate: () => setResult(null),
    mutationFn: () =>
      api.post("/questions/import/paste", { ...paste, organization_id: organizationId }),
    onSuccess: (r) => {
      done(r);
      setPaste((p) => ({ ...p, text: "" }));
      setActiveTab("browse");
    },
  });
  const fileImport = useMutation({
    onMutate: () => setResult(null),
    mutationFn: (f: File) => {
      const fd = new FormData();
      fd.append("file", f);
      return api.post("/questions/import/file", fd, orgParams);
    },
    onSuccess: (r) => {
      done(r);
      setActiveTab("browse");
    },
  });
  const transition = useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) =>
      api.post(`/questions/${id}/transition`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["questions"] }),
  });
  const promote = useMutation({
    mutationFn: (id: string) => api.post(`/questions/${id}/promote`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["questions"] }),
  });

  return (
    <div className="max-w-6xl space-y-6">
      <PageHeader
        title={admin ? "Platform Question Review" : "Company Question Bank"}
        description={
          admin
            ? "Review and validate questions across the platform."
            : "Company-private repository: questions are securely isolated to your company and automatically reused across all role assessments."
        }
        actions={
          !admin ? (
            <div className="flex items-center gap-2">
              <span className="inline-flex items-center gap-1 text-xs font-semibold px-2.5 py-1 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                🔒 Company Private
              </span>
            </div>
          ) : null
        }
      />

      <ImportResult r={result} />

      {!admin && (
        <Tabs
          tabs={[
            { id: "browse", label: `Browse Bank (${list.data?.length ?? 0})` },
            { id: "add", label: "Add Question" },
            { id: "import", label: "Import CSV / Paste" },
          ]}
          current={activeTab}
          onChange={(t) => setActiveTab(t as any)}
        />
      )}

      {activeTab === "add" && !admin && (
        <Card title="Add a Company-Private Question" description="Created questions are available immediately for assessments across all jobs in your company.">
          <div className="space-y-4 max-w-2xl">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-700">Question Text *</label>
              <textarea
                className={inputCls}
                rows={3}
                placeholder="Enter prompt or problem statement…"
                value={form.question_text}
                onChange={(e) => setForm({ ...form, question_text: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="space-y-1">
                <label htmlFor="qb-domain" className="text-xs font-medium text-gray-700">Used in</label>
                <select
                  id="qb-domain"
                  className={inputCls}
                  value={form.domain}
                  onChange={(e) => setForm({ ...form, domain: e.target.value, category: "", skill: "" })}
                  data-testid="qb-domain"
                >
                  {DOMAIN_OPTIONS.map(([v, l]) => (
                    <option key={v} value={v}>{l}</option>
                  ))}
                </select>
              </div>
              {form.domain === "TECHNICAL" && (
                <div className="space-y-1">
                  <label htmlFor="qb-type" className="text-xs font-medium text-gray-700">Type</label>
                  <select id="qb-type" className={inputCls} value={form.question_type} onChange={(e) => setForm({ ...form, question_type: e.target.value })}>
                    <option value="TECHNICAL">Written</option>
                    <option value="MCQ">Multiple choice</option>
                  </select>
                </div>
              )}
              {(form.domain === "APTITUDE" || form.domain === "HR_INTERVIEW") ? (
                <div className="space-y-1">
                  <label htmlFor="qb-category" className="text-xs font-medium text-gray-700">Category *</label>
                  <select id="qb-category" className={inputCls} value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })} data-testid="qb-category">
                    <option value="">Choose…</option>
                    {(form.domain === "APTITUDE" ? APTITUDE_CATEGORIES : Object.keys(HR_CATEGORY_LABEL)).map((c) => (
                      <option key={c} value={c}>{form.domain === "HR_INTERVIEW" ? HR_CATEGORY_LABEL[c] : c}</option>
                    ))}
                  </select>
                </div>
              ) : (
                <div className="space-y-1">
                  <label htmlFor="qb-skill" className="text-xs font-medium text-gray-700">Skill / Competency *</label>
                  <input id="qb-skill" className={inputCls} placeholder="e.g. Python, SQL" value={form.skill} onChange={(e) => setForm({ ...form, skill: e.target.value })} />
                </div>
              )}
              {form.domain !== "HR_INTERVIEW" && (
                <div className="space-y-1">
                  <label htmlFor="qb-diff" className="text-xs font-medium text-gray-700">Difficulty</label>
                  <select id="qb-diff" className={inputCls} value={form.difficulty} onChange={(e) => setForm({ ...form, difficulty: e.target.value })}>
                    <option value="easy">Easy</option>
                    <option value="medium">Medium</option>
                    <option value="hard">Hard</option>
                  </select>
                </div>
              )}
            </div>
            {form.domain === "HR_INTERVIEW" && (
              <p className="text-xs text-gray-500 rounded-md bg-gray-50 border border-gray-200 p-2.5">
                HR questions must be job-relevant. Anything touching protected or sensitive topics (religion, family plans, health, age and similar) is rejected.
              </p>
            )}

            {(form.domain === "APTITUDE" || (form.domain === "TECHNICAL" && form.question_type === "MCQ")) && (
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-gray-100">
                <div className="sm:col-span-2 space-y-1">
                  <label className="text-xs font-medium text-gray-700">Options (separated by |)</label>
                  <input
                    className={inputCls}
                    placeholder="Option A | Option B | Option C | Option D"
                    value={form.options}
                    onChange={(e) => setForm({ ...form, options: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-700">Correct Option Index (0-based)</label>
                  <input
                    className={inputCls}
                    type="number"
                    min={0}
                    value={form.correct_option}
                    onChange={(e) => setForm({ ...form, correct_option: e.target.value })}
                  />
                </div>
              </div>
            )}

            {(form.domain === "TECHNICAL_INTERVIEW" || (form.domain === "TECHNICAL" && form.question_type === "TECHNICAL")) && (
              <div className="space-y-3 pt-2 border-t border-gray-100">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-700">Expected Key Concepts (optional, separated by |)</label>
                  <input
                    className={inputCls}
                    placeholder="e.g. asynchronous execution | event loop | non-blocking I/O"
                    value={form.expected_concepts}
                    onChange={(e) => setForm({ ...form, expected_concepts: e.target.value })}
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-700">Evaluation Criteria (optional, separated by |)</label>
                  <input
                    className={inputCls}
                    placeholder="e.g. correctness | clarity | mentions performance implications"
                    value={form.criteria}
                    onChange={(e) => setForm({ ...form, criteria: e.target.value })}
                  />
                </div>
              </div>
            )}

            {form.domain === "CODING" && (
              <div className="space-y-1 pt-2 border-t border-gray-100">
                <label className="text-xs font-medium text-gray-700">Test Cases JSON</label>
                <textarea
                  className={`${inputCls} font-mono text-xs`}
                  rows={3}
                  placeholder='[{"input": "[1, 2]", "expected_output": "3"}]'
                  value={form.test_cases}
                  onChange={(e) => setForm({ ...form, test_cases: e.target.value })}
                />
              </div>
            )}

            <div className="flex gap-2 pt-2">
              <Button
                onClick={() => create.mutate()}
                disabled={create.isPending || !form.question_text || (["APTITUDE", "HR_INTERVIEW"].includes(form.domain) ? !form.category : !form.skill)}
              >
                {create.isPending ? "Validating…" : "Add to Question Bank"}
              </Button>
              <Button variant="secondary" onClick={() => setActiveTab("browse")}>
                Cancel
              </Button>
            </div>
            <ErrorBox error={create.error} />
          </div>
        </Card>
      )}

      {activeTab === "import" && !admin && (
        <div className="grid md:grid-cols-2 gap-5">
          <Card title="Batch File Upload" description="Upload CSV or JSON file containing questions.">
            <div className="space-y-3">
              <input
                type="file"
                accept=".csv,.json"
                className="text-sm"
                onChange={(e) => e.target.files?.[0] && fileImport.mutate(e.target.files[0])}
              />
              <p className="text-xs text-gray-500">
                Supported columns: question_text, question_type, skill, difficulty, options, correct_option, expected_concepts, test_cases. This quick import saves
                immediately. For an import you can review first (Excel template, validation, duplicate check), use <b>Question bank</b> inside a job.
              </p>
              <ErrorBox error={fileImport.error} />
            </div>
          </Card>

          <Card title="Quick Paste Import" description="Paste questions separated by blank lines.">
            <div className="space-y-3">
              <textarea
                className={inputCls}
                rows={4}
                placeholder="Paste question blocks here…"
                value={paste.text}
                onChange={(e) => setPaste({ ...paste, text: e.target.value })}
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  className={inputCls}
                  placeholder="Target skill name"
                  value={paste.skill}
                  onChange={(e) => setPaste({ ...paste, skill: e.target.value })}
                />
                <Button
                  variant="secondary"
                  onClick={() => pasteImport.mutate()}
                  disabled={pasteImport.isPending || !paste.text || !paste.skill}
                >
                  Import Pasted Text
                </Button>
              </div>
              <ErrorBox error={pasteImport.error} />
            </div>
          </Card>
        </div>
      )}

      {(activeTab === "browse" || admin) && (
        <Card
          title="Bank Questions"
          description="Browse and manage all questions stored for this workspace."
          actions={
            !admin ? (
              <Button size="sm" onClick={() => setActiveTab("add")}>
                + Add Question
              </Button>
            ) : null
          }
        >
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter by where the question is used" data-testid="domain-filter">
            {[["", "All"], ...DOMAIN_OPTIONS.map(([v, l]) => [v, l.replace(" assessment", "")])].map(([v, l]) => (
              <button
                key={v || "all"}
                type="button"
                aria-pressed={filters.domain === v}
                onClick={() => setFilters({ ...filters, domain: v })}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${filters.domain === v ? "border-blue-600 bg-blue-600 text-white" : "border-gray-300 bg-white text-gray-700 hover:bg-gray-50"}`}
              >
                {l}
              </button>
            ))}
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <input
              className={inputCls}
              aria-label="Search by question text"
              placeholder="Search by question text…"
              value={filters.q}
              onChange={(e) => setFilters({ ...filters, q: e.target.value })}
            />
            <select
              className={inputCls}
              aria-label="Filter by status"
              value={filters.status}
              onChange={(e) => setFilters({ ...filters, status: e.target.value })}
            >
              <option value="">All Statuses</option>
              {Object.keys(NEXT).map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
            <select
              className={inputCls}
              aria-label="Filter by origin"
              value={filters.source_type}
              onChange={(e) => setFilters({ ...filters, source_type: e.target.value })}
            >
              <option value="">All Origins</option>
              <option value="COMPANY_PRIVATE">Company Private</option>
              <option value="PLATFORM">Platform Public</option>
              <option value="AI_GENERATED">AI Generated</option>
            </select>
          </div>

          {list.isLoading && <Loading />}
          <ErrorBox error={list.error || transition.error || promote.error} onRetry={list.refetch} />

          {list.data?.length === 0 && !list.isLoading && (
            <Empty
              action={
                !admin ? (
                  <Button size="sm" onClick={() => setActiveTab("add")}>
                    Add your first question
                  </Button>
                ) : null
              }
            >
              No questions found matching your criteria.
            </Empty>
          )}

          {list.data?.length > 0 && (
            <Table head={["Question", filters.domain === "APTITUDE" || filters.domain === "HR_INTERVIEW" ? "Category" : "Skill / category", "Type", "Origin", "Status", "Actions"]}>
              {list.data.map((q: any) => (
                <tr key={q.id} className="align-top hover:bg-gray-50/50">
                  <td className="py-2.5 pr-3 max-w-md">
                    <p className="text-gray-900 text-xs font-medium leading-relaxed">{q.question_text}</p>
                    {(q.source_refs ?? []).length > 0 && (
                      <div className="text-[11px] text-gray-400 mt-1">
                        Grounded on: {q.source_refs.map((r: any) => r.title).join(", ")}
                      </div>
                    )}
                  </td>
                  <td className="pr-3 text-xs font-medium text-gray-700 whitespace-nowrap">{q.skill_name ?? (q.domain === "HR_INTERVIEW" ? HR_CATEGORY_LABEL[q.category] ?? q.category : q.category) ?? "—"}<span className="block text-[11px] font-normal text-gray-400">{DOMAIN_LABEL[q.domain] ?? "Technical"}</span></td>
                  <td className="pr-3">
                    <Badge tone="gray">{questionTypeLabel(q.question_type)}</Badge>
                  </td>
                  <td className="pr-3 text-xs text-gray-500 whitespace-nowrap">{humanize(q.source_type)}</td>
                  <td className="pr-3">
                    <Badge>{q.status}</Badge>
                  </td>
                  <td className="space-x-1.5 whitespace-nowrap">
                    {(NEXT[q.status] ?? []).map((s) => (
                      <button
                        key={s}
                        className="text-xs font-medium text-blue-600 hover:text-blue-800 underline disabled:opacity-40"
                        disabled={transition.isPending}
                        onClick={() => transition.mutate({ id: q.id, status: s })}
                      >
                        {s.toLowerCase()}
                      </button>
                    ))}
                    {admin && q.visibility !== "PLATFORM_PUBLIC" && ["APPROVED", "ACTIVE"].includes(q.status) && (
                      <button
                        className="text-xs font-medium text-purple-600 hover:text-purple-800 underline ml-1"
                        onClick={() => promote.mutate(q.id)}
                      >
                        Promote to platform
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </Table>
          )}
        </Card>
      )}
    </div>
  );
}
