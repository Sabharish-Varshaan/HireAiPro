import Editor from "@monaco-editor/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, inputCls } from "../../components/ui";

type Lang = { id: string; display_name: string; monaco: string; judge0_language_id: number | null; available: boolean };

const RESULT_LABEL: Record<string, string> = {
  ALL_TESTS_PASSED: "All hidden tests passed",
  SOME_TESTS_FAILED: "Some hidden tests failed",
  COMPILE_OR_RUNTIME_ERROR: "Compile or runtime error",
};

// Minimal honest templates: they read the test input and print, nothing more.
const TEMPLATES: Record<string, string> = {
  python: `import sys


def solve(data: str) -> str:
    # data is the whole test input from stdin, e.g. "[1, 2, 3]"
    ...


if __name__ == "__main__":
    print(solve(sys.stdin.read()))
`,
  javascript: `const data = require("fs").readFileSync(0, "utf8"); // whole test input from stdin

function solve(data) {
  // return the answer to print
}

console.log(solve(data));
`,
  cpp: `#include <bits/stdc++.h>
using namespace std;

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);

    // whole test input from stdin
    string data((istreambuf_iterator<char>(cin)), istreambuf_iterator<char>());

    // compute the answer and print it with cout

    return 0;
}
`,
};

export function CodingQuestion({ aqId, question, savedText, saveAndGetAnswerId }: {
  aqId: string; question: any; savedText?: string | null;
  // One upsert that stores the source and returns the answer id (never two parallel saves).
  saveAndGetAnswerId: (text: string) => Promise<string>;
}) {
  const langs = useQuery({ queryKey: ["coding-languages"], queryFn: () => api.get("/coding/languages").then((r) => r.data as Lang[]), staleTime: 60_000 });
  const allowed = (langs.data ?? []).filter((l) => !question.allowed_languages || question.allowed_languages.includes(l.id));
  const [lang, setLang] = useState<string>("python");
  // One draft per language, so switching never submits Python source as C++.
  const [drafts, setDrafts] = useState<Record<string, string>>(() => ({
    python: savedText || question.starter_code || TEMPLATES.python,
  }));
  const current = allowed.find((l) => l.id === lang) ?? allowed[0];
  const source = drafts[current?.id ?? lang] ?? TEMPLATES[current?.id ?? lang];
  const [result, setResult] = useState<any>(null);

  const [runResult, setRunResult] = useState<any>(null);
  const [custom, setCustom] = useState("");
  const [showCustom, setShowCustom] = useState(false);
  const samples: { input: string; expected_output: string }[] = question.sample_tests ?? [];

  const body = (answerId: string) => ({ assessment_answer_id: answerId, question_id: question.id, language: current!.id, source_code: source });
  const runSamples = useMutation({
    mutationFn: async () => {
      const answerId = await saveAndGetAnswerId(source);
      return (await api.post("/coding/run", { ...body(answerId), custom_input: showCustom && custom ? custom : null })).data;
    },
    onMutate: () => setRunResult(null),
    onSuccess: setRunResult,
  });
  const run = useMutation({  // Submit: all hidden tests, scored
    mutationFn: async () => {
      const answerId = await saveAndGetAnswerId(source);
      return (await api.post("/coding/submit", body(answerId))).data;
    },
    onMutate: () => setResult(null),
    onSuccess: setResult,
  });
  const busy = run.isPending || runSamples.isPending;

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor={`lang-${aqId}`} className="text-gray-600">Language</label>
        <select id={`lang-${aqId}`} className={`${inputCls} w-52`} value={current?.id ?? ""} disabled={busy || !allowed.length}
          onChange={(e) => setLang(e.target.value)}>
          {allowed.map((l) => <option key={l.id} value={l.id} disabled={!l.available}>{l.display_name}{l.available ? "" : " (unavailable)"}</option>)}
        </select>
        {current && !current.available && <span className="text-xs text-amber-700">Code runner unavailable — you can keep editing and retry.</span>}
      </div>
      <p className="text-xs text-gray-500">
        Your program reads the test input from <b>standard input</b> and prints the answer to <b>standard output</b> (surrounding whitespace ignored).
        <b> Run</b> checks the sample tests below. <b>Submit code</b> grades against all tests{question.hidden_test_count ? ` (${question.hidden_test_count} hidden)` : ""}; hidden inputs and outputs are never shown.
      </p>
      {samples.length > 0 && (
        <div className="text-xs space-y-1" data-testid="samples">
          <p className="font-medium">Sample tests</p>
          {samples.map((t, i) => (
            <div key={i} className="grid grid-cols-2 gap-2 bg-gray-50 border border-gray-200 rounded p-1.5">
              <div><span className="text-gray-500">Input</span><pre className="whitespace-pre-wrap">{t.input}</pre></div>
              <div><span className="text-gray-500">Expected output</span><pre className="whitespace-pre-wrap">{t.expected_output}</pre></div>
            </div>))}
        </div>
      )}
      {current && (
        <Editor key={`${aqId}-${current.id}`} height="260px" language={current.monaco} value={source}
          onChange={(v) => setDrafts((d) => ({ ...d, [current.id]: v ?? "" }))}
          options={{ minimap: { enabled: false }, fontSize: 13 }} />
      )}
      {showCustom && <textarea className="w-full border border-gray-300 rounded-md p-2 text-xs font-mono" rows={3} placeholder="Custom input (stdin)" value={custom} onChange={(e) => setCustom(e.target.value)} />}
      <div className="flex flex-wrap gap-2 items-center">
        <Button variant="secondary" disabled={busy || !current?.available} onClick={() => runSamples.mutate()}>
          {runSamples.isPending ? "Running…" : "Run (samples)"}</Button>
        <Button disabled={busy || !current?.available} onClick={() => run.mutate()}>
          {run.isPending ? `Grading in Judge0 (${current?.display_name})…` : `Submit code (${current?.display_name ?? "…"})`}</Button>
        <button type="button" className="text-xs underline text-gray-600" onClick={() => setShowCustom((v) => !v)}>{showCustom ? "Hide custom input" : "Try custom input"}</button>
      </div>
      <ErrorBox error={run.error || runSamples.error || langs.error} />
      {runResult && (
        <div className="text-xs space-y-1" data-testid="run-result">
          {runResult.samples.map((t: any) => (
            <p key={t.index}><Badge tone={t.passed ? "green" : "red"}>{t.passed ? "PASS" : "FAIL"}</Badge> Sample {t.index + 1}: {t.status}
              {!t.passed && t.stdout != null && <> — your output <code>{t.stdout.trim().slice(0, 120)}</code></>}
              {t.stderr && <pre className="text-red-600 whitespace-pre-wrap">{t.stderr.slice(0, 300)}</pre>}</p>))}
          {runResult.custom && <div><span className="text-gray-500">Custom input → </span><Badge>{runResult.custom.status}</Badge><pre className="whitespace-pre-wrap">{runResult.custom.stdout}</pre>
            {runResult.custom.stderr && <pre className="text-red-600 whitespace-pre-wrap">{runResult.custom.stderr}</pre>}</div>}
        </div>
      )}
      {result && (
        <div className="text-xs space-y-1" data-testid="coding-result">
          <p><b>{RESULT_LABEL[result.result] ?? result.result}</b> · {result.language} · <Badge>{result.execution_backend}</Badge></p>
          {result.message && <pre className="text-red-600 whitespace-pre-wrap">{result.message.slice(0, 400)}</pre>}
          {result.execution_backend?.includes("local_fallback") && (
            <p className="text-amber-700">Executed by the local development fallback, not the Judge0 sandbox. Development only.</p>
          )}
        </div>
      )}
    </div>
  );
}
