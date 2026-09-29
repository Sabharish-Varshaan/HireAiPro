import Editor from "@monaco-editor/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, humanize, inputCls } from "../../components/ui";

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

export function CodingQuestion({
  aqId,
  question,
  savedText,
  saveAndGetAnswerId,
}: {
  aqId: string;
  question: any;
  savedText?: string | null;
  // One upsert that stores the source and returns the answer id (never two parallel saves).
  saveAndGetAnswerId: (text: string) => Promise<string>;
}) {
  const langs = useQuery({
    queryKey: ["coding-languages"],
    queryFn: () => api.get("/coding/languages").then((r) => r.data as Lang[]),
    staleTime: 60_000,
  });
  const allowed = (langs.data ?? []).filter(
    (l) => !question.allowed_languages || question.allowed_languages.includes(l.id)
  );
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

  const body = (answerId: string) => ({
    assessment_answer_id: answerId,
    question_id: question.id,
    language: current!.id,
    source_code: source,
  });
  const runSamples = useMutation({
    mutationFn: async () => {
      const answerId = await saveAndGetAnswerId(source);
      return (
        await api.post("/coding/run", {
          ...body(answerId),
          custom_input: showCustom && custom ? custom : null,
        })
      ).data;
    },
    onMutate: () => setRunResult(null),
    onSuccess: setRunResult,
  });
  const run = useMutation({
    // Submit: all hidden tests, scored
    mutationFn: async () => {
      const answerId = await saveAndGetAnswerId(source);
      return (await api.post("/coding/submit", body(answerId))).data;
    },
    onMutate: () => setResult(null),
    onSuccess: setResult,
  });
  const busy = run.isPending || runSamples.isPending;

  return (
    <div className="space-y-3">
      {/* Language Selector & Instructions */}
      <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
        <div className="flex items-center gap-2">
          <label htmlFor={`lang-${aqId}`} className="font-semibold text-gray-700">
            Language:
          </label>
          <select
            id={`lang-${aqId}`}
            className={`${inputCls} w-48`}
            value={current?.id ?? ""}
            disabled={busy || !allowed.length}
            onChange={(e) => setLang(e.target.value)}
          >
            {allowed.map((l) => (
              <option key={l.id} value={l.id} disabled={!l.available}>
                {l.display_name}
                {l.available ? "" : " (unavailable)"}
              </option>
            ))}
          </select>
        </div>
        {current && !current.available && (
          <span className="text-xs text-amber-700 bg-amber-50 px-2.5 py-1 rounded border border-amber-200">
            Runner temporarily unavailable — edit and retry shortly.
          </span>
        )}
      </div>

      <div className="p-3 bg-gray-50 border border-gray-200 rounded-lg text-xs text-gray-600 leading-relaxed">
        Reads test input from <b>standard input</b> and prints answer to <b>standard output</b>.
        Use <b>Run (samples)</b> to test against visible sample inputs. Use <b>Submit Code</b> to evaluate all tests
        {question.hidden_test_count ? ` (${question.hidden_test_count} hidden)` : ""}.
      </div>

      {/* Visible Samples */}
      {samples.length > 0 && (
        <div className="space-y-1.5" data-testid="samples">
          <p className="text-xs font-semibold text-gray-700">Sample Test Cases</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
            {samples.map((t, i) => (
              <div key={i} className="bg-gray-50 border border-gray-200 rounded-lg p-2.5 space-y-1">
                <span className="text-gray-400 font-semibold block text-[11px]">Sample {i + 1}</span>
                <div className="grid grid-cols-2 gap-2 font-mono">
                  <div>
                    <span className="text-gray-500 block text-[10px]">Input:</span>
                    <pre className="bg-white p-1 rounded border border-gray-100 whitespace-pre-wrap">{t.input}</pre>
                  </div>
                  <div>
                    <span className="text-gray-500 block text-[10px]">Expected:</span>
                    <pre className="bg-white p-1 rounded border border-gray-100 whitespace-pre-wrap">{t.expected_output}</pre>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Monaco Code Editor Workspace */}
      <div className="border border-gray-300 rounded-xl overflow-hidden shadow-inner">
        {current && (
          <Editor
            key={`${aqId}-${current.id}`}
            height="300px"
            language={current.monaco}
            value={source}
            onChange={(v) => setDrafts((d) => ({ ...d, [current.id]: v ?? "" }))}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              scrollBeyondLastLine: false,
              lineNumbers: "on",
              tabSize: 4,
            }}
          />
        )}
      </div>

      {showCustom && (
        <div className="space-y-1">
          <label className="text-xs font-medium text-gray-700">Custom Standard Input (stdin)</label>
          <textarea
            className="w-full border border-gray-300 rounded-lg p-2.5 text-xs font-mono focus:border-blue-600 focus:outline-none"
            rows={3}
            placeholder="Type custom test input here…"
            value={custom}
            onChange={(e) => setCustom(e.target.value)}
          />
        </div>
      )}

      {/* Action Controls: Run (secondary) vs Submit (primary) */}
      <div className="flex flex-wrap gap-2.5 items-center pt-1">
        <Button
          variant="secondary"
          size="sm"
          disabled={busy || !current?.available}
          onClick={() => runSamples.mutate()}
        >
          {runSamples.isPending ? "Running samples…" : "▶ Run (samples)"}
        </Button>

        <Button
          size="sm"
          disabled={busy || !current?.available}
          onClick={() => run.mutate()}
        >
          {run.isPending
            ? `Grading your code (${current?.display_name})…`
            : `Submit Code (${current?.display_name ?? "…"})`}
        </Button>

        <button
          type="button"
          className="text-xs font-medium underline text-gray-600 hover:text-gray-900 ml-auto"
          onClick={() => setShowCustom((v) => !v)}
        >
          {showCustom ? "Hide custom input" : "Try custom input"}
        </button>
      </div>

      <ErrorBox error={run.error || runSamples.error || langs.error} />

      {/* Sample Execution Results */}
      {runResult && (
        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-xs space-y-2" data-testid="run-result">
          <p className="font-semibold text-gray-800">Sample Execution Output</p>
          {runResult.samples.map((t: any) => (
            <div key={t.index} className="flex items-start gap-2">
              <Badge tone={t.passed ? "green" : "red"}>{t.passed ? "PASS" : "FAIL"}</Badge>
              <div className="space-y-0.5">
                <span className="font-medium">
                  Sample {t.index + 1}: {humanize(t.status)}
                </span>
                {!t.passed && t.stdout != null && (
                  <p className="font-mono text-gray-600">
                    Your output: <code>{t.stdout.trim().slice(0, 120)}</code>
                  </p>
                )}
                {t.stderr && (
                  <pre className="text-red-600 bg-red-50 p-1.5 rounded font-mono text-[11px] whitespace-pre-wrap">
                    {t.stderr.slice(0, 300)}
                  </pre>
                )}
              </div>
            </div>
          ))}
          {runResult.custom && (
            <div className="pt-2 border-t border-gray-200 space-y-1">
              <div className="flex items-center gap-2">
                <span className="font-semibold text-gray-700">Custom Input Result:</span>
                <Badge>{runResult.custom.status}</Badge>
              </div>
              <pre className="bg-white p-2 rounded border border-gray-200 font-mono text-[11px] whitespace-pre-wrap">
                {runResult.custom.stdout}
              </pre>
              {runResult.custom.stderr && (
                <pre className="text-red-600 bg-red-50 p-2 rounded font-mono text-[11px] whitespace-pre-wrap">
                  {runResult.custom.stderr}
                </pre>
              )}
            </div>
          )}
        </div>
      )}

      {/* Submission Final Scored Results */}
      {result && (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs space-y-1.5" data-testid="coding-result">
          <div className="flex items-center gap-2">
            <span className="font-bold text-blue-950">
              {RESULT_LABEL[result.result] ?? result.result}
            </span>
            <span>·</span>
            <span className="font-medium text-blue-900">{result.language}</span>
            <Badge>{result.execution_backend}</Badge>
          </div>
          {result.message && (
            <pre className="text-red-700 bg-red-50 p-2 rounded font-mono text-[11px] whitespace-pre-wrap">
              {result.message.slice(0, 400)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
