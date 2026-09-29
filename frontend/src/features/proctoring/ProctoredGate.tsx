import { type ReactNode, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Button, ErrorBox, Loading } from "../../components/ui";
import { useProctoring } from "./useProctoring";

const CHECK_LABEL: Record<string, string> = {
  camera: "Camera", microphone: "Microphone", audio_signal: "Microphone signal", network: "Connection to HireAiPro",
  fullscreen_capable: "Fullscreen supported", browser: "Browser compatible",
};

/**
 * Consent → system check → fullscreen start → monitored children.
 * `children` receives `complete` so the runner can end the session on submit.
 */
export function ProctoredGate({ applicationId, kind, children }: {
  applicationId: string; kind: "ASSESSMENT" | "INTERVIEW";
  children: (complete: () => Promise<void>, stream: MediaStream | null) => ReactNode;
}) {
  const p = useProctoring(applicationId, kind);
  const policy = useQuery({ queryKey: ["proctor-policy"], queryFn: () => api.get("/proctoring/policy").then((r) => r.data) });
  const video = useRef<HTMLVideoElement>(null);
  const [checking, setChecking] = useState(false);
  const [missing, setMissing] = useState<string[]>([]);
  const label = kind === "ASSESSMENT" ? "assessment" : "interview";

  if (p.phase === "loading") return <Loading label="Preparing session…" />;
  if (p.phase === "error") return <ErrorBox error={p.error} />;
  if (p.phase === "completed") return <>{children(p.complete, null)}</>;

  if (p.phase === "consent") return (
    <div className="space-y-3 text-sm" data-testid="proctor-consent">
      <p className="font-medium">Before you start this {label}</p>
      <p className="text-gray-600">This {label} is proctored. While it is open, HireAiPro records the following as timestamped events for the hiring team (and your institution) to review:</p>
      <ul className="list-disc pl-5 text-gray-600">{(policy.data?.monitored ?? []).map((m: string) => <li key={m}>{m}</li>)}</ul>
      <p className="text-gray-600">HireAiPro does <b>not</b> do:</p>
      <ul className="list-disc pl-5 text-gray-600">{(policy.data?.not_monitored ?? []).map((m: string) => <li key={m}>{m}</li>)}</ul>
      <p className="text-gray-600">Events are facts, not verdicts: a person reviews them and no decision is made automatically. Your camera and microphone stay on your device and are released when you finish.</p>
      <Button onClick={() => p.consent()}>I understand and agree</Button>
    </div>
  );

  if (p.phase === "check" || p.phase === "ready") return (
    <div className="space-y-3 text-sm" data-testid="proctor-check">
      <p className="font-medium">System check</p>
      <div className="flex gap-4 flex-wrap">
        <video ref={video} muted playsInline className="w-56 h-40 bg-gray-900 rounded" data-testid="camera-preview" />
        <div className="space-y-1 min-w-[220px]">
          <div className="text-xs text-gray-500">Microphone level (speak to test)</div>
          <div className="h-2 bg-gray-200 rounded w-48"><div className="h-2 bg-green-500 rounded" style={{ width: `${Math.min(100, p.level * 800)}%` }} /></div>
          {p.checks && Object.entries(CHECK_LABEL).map(([k, name]) => (
            <div key={k} className="flex items-center gap-2 text-xs">
              <Badge tone={(p.checks as any)[k] ? "green" : "red"}>{(p.checks as any)[k] ? "OK" : "FAILED"}</Badge>{name}
              {k === "network" && p.checks?.network_latency_ms != null && <span className="text-gray-400">{p.checks.network_latency_ms} ms</span>}
            </div>
          ))}
        </div>
      </div>
      {missing.length > 0 && <p className="text-red-600 text-xs">Required checks not passed: {missing.map((m) => CHECK_LABEL[m] ?? m).join(", ")}. Fix these and run the check again.</p>}
      {p.error && <p className="text-red-600 text-xs">{p.error}</p>}
      <div className="flex gap-2">
        <Button variant={p.phase === "ready" ? "secondary" : "primary"} disabled={checking} onClick={async () => {
          setChecking(true);
          try { const r = await p.runSystemCheck(video.current); setMissing(r?.missing ?? []); } finally { setChecking(false); }
        }}>{checking ? "Checking… (speak now)" : p.checks ? "Run check again" : "Run system check"}</Button>
        {p.phase === "ready" && <Button onClick={() => p.start()}>Enter fullscreen and start {label}</Button>}
      </div>
    </div>
  );

  // active
  return (
    <div data-testid="proctor-active">
      {p.warnings.fullscreen && (
        <div className="mb-3 p-2 rounded bg-amber-50 border border-amber-300 text-sm flex items-center gap-3" role="alert">
          Please return to fullscreen. This event has been recorded.
          <Button variant="secondary" onClick={p.returnToFullscreen}>Return to fullscreen</Button>
        </div>
      )}
      {(p.warnings.camera || p.warnings.mic) && (
        <div className="mb-3 p-2 rounded bg-amber-50 border border-amber-300 text-sm" role="alert">
          {p.warnings.camera ? "Your camera stopped. " : ""}{p.warnings.mic ? "Your microphone stopped. " : ""}This event has been recorded. Reconnect the device to continue normally.
        </div>
      )}
      {p.warnings.offline && (
        <div className="mb-3 p-2 rounded bg-amber-50 border border-amber-300 text-sm" role="alert">You appear to be offline. Your work is kept; reconnect to continue.</div>
      )}
      <div className="text-xs text-gray-500 mb-2 flex items-center gap-2"><span className="inline-block w-2 h-2 rounded-full bg-red-500" />Proctored session active (camera and microphone in use, nothing is recorded)</div>
      {children(p.complete, p.stream.current)}
    </div>
  );
}
