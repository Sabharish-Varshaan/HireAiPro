import Editor from "@monaco-editor/react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, inputCls } from "../../components/ui";

type Lang = { id: string; display_name: string; monaco: string; judge0_language_id: number | null; available: boolean };

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

  const run = useMutation({
    mutationFn: async () => {
      const answerId = await saveAndGetAnswerId(source);
      return (await api.post("/coding/submit", { assessment_answer_id: answerId, question_id: question.id, language: current!.id, source_code: source })).data;
    },
    onMutate: () => setResult(null),
    onSuccess: setResult,
  });

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label htmlFor={`lang-${aqId}`} className="text-gray-600">Language</label>
        <select id={`lang-${aqId}`} className={`${inputCls} w-52`} value={current?.id ?? ""} disabled={run.isPending || !allowed.length}
          onChange={(e) => setLang(e.target.value)}>
          {allowed.map((l) => <option key={l.id} value={l.id} disabled={!l.available}>{l.display_name}{l.available ? "" : " (unavailable)"}</option>)}
        </select>
        {current && !current.available && <span className="text-xs text-amber-700">Code runner unavailable — you can keep editing and retry.</span>}
      </div>
      <p className="text-xs text-gray-500">
        Your program reads each hidden test's input from <b>standard input</b> and must print the answer to <b>standard output</b>.
        The output is compared with the expected output (surrounding whitespace ignored). Test inputs and outputs are not shown.
      </p>
      {current && (
        <Editor key={`${aqId}-${current.id}`} height="260px" language={current.monaco} value={source}
          onChange={(v) => setDrafts((d) => ({ ...d, [current.id]: v ?? "" }))}
          options={{ minimap: { enabled: false }, fontSize: 13 }} />
      )}
      <Button variant="secondary" disabled={run.isPending || !current?.available} onClick={() => run.mutate()}>
        {run.isPending ? `Running in Judge0 (${current?.display_name})…` : `Run tests (${current?.display_name ?? "…"})`}
      </Button>
      <ErrorBox error={run.error || langs.error} />
      {result && (
        <div className="text-xs space-y-1" data-testid="coding-result">
          <p><b>{result.passed_count}/{result.total_count}</b> hidden tests passed · {result.language} · <Badge>{result.execution_backend}</Badge></p>
          {result.tests.map((t: any) => (
            <p key={t.index}>Test {t.index + 1}: {t.passed ? "passed" : "failed"} ({t.status})
              {t.stderr && <span className="text-red-600"> {t.stderr.slice(0, 200)}</span>}</p>
          ))}
          {result.tests.some((t: any) => t.execution_backend === "local_fallback") && (
            <p className="text-amber-700">Executed by the local development fallback, not the Judge0 sandbox. Development only.</p>
          )}
        </div>
      )}
    </div>
  );
}
