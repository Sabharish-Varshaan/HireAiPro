import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { Badge, Button, Empty, ErrorBox, Loading, Table } from "../../components/ui";

const fmt = (ms: number | null | undefined) => ms == null ? "—" : ms < 60_000 ? `${Math.round(ms / 1000)}s` : `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`;

const COUNT_KEYS = ["fullscreen_exits", "tab_switches", "window_blurs", "camera_interruptions", "microphone_interruptions",
  "network_outages", "heartbeat_interruptions"];

/** Reviewer view of objective proctoring events. Facts only, no verdict. */
export function ProctoringPanel({ applicationId }: { applicationId: string }) {
  const q = useQuery({ queryKey: ["proctoring-review", applicationId],
    queryFn: () => api.get(`/proctoring/review/by-application/${applicationId}`).then((r) => r.data) });
  const [open, setOpen] = useState<string | null>(null);
  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  const sessions: any[] = q.data.sessions ?? [];
  if (!sessions.length) return <Empty>No proctored sessions for this application.</Empty>;
  return (
    <div className="space-y-3 text-sm" data-testid="proctoring-panel">
      <p className="text-xs text-gray-500">{q.data.note}</p>
      {sessions.map((s) => {
        const c = Object.fromEntries(COUNT_KEYS.map((k) => [k, s.summary[k] ?? 0]));
        return (
          <div key={s.session_id} className="border border-gray-200 rounded-md p-3 space-y-2">
            <div className="flex items-center gap-2"><b>{s.kind === "ASSESSMENT" ? "Assessment" : "Interview"}</b><Badge>{s.session_status}</Badge>
              <span className="text-xs text-gray-500">duration {fmt(s.summary.session_duration_seconds != null ? s.summary.session_duration_seconds * 1000 : null)} · consent {s.consent_at ? new Date(s.consent_at).toLocaleString() : "not given"}</span></div>
            <div className="flex flex-wrap gap-1 text-xs">
              {Object.entries(c).map(([k, v]) => <Badge key={k} tone={(v as number) > 0 ? "amber" : "gray"}>{`${k.replaceAll("_", " ")}: ${v}`}</Badge>)}
              <Badge tone="gray">{`time tab hidden: ${fmt(s.summary.time_tab_hidden_ms)}`}</Badge>
              <Badge tone="gray">{`time disconnected: ${fmt(s.summary.time_disconnected_ms)}`}</Badge>
            </div>
            <Button variant="secondary" onClick={() => setOpen(open === s.session_id ? null : s.session_id)}>
              {open === s.session_id ? "Hide timeline" : "View Timeline"}</Button>
            {open === s.session_id && (
              <Table head={["Time", "Event", "Duration", "Source"]}>{s.timeline.map((e: any, i: number) => (
                <tr key={i} className={e.severity === "notice" ? "bg-amber-50" : ""}>
                  <td className="pr-3 text-xs">{new Date(e.occurred_at).toLocaleTimeString()}</td>
                  <td className="pr-3">{e.event_type}</td><td className="pr-3">{fmt(e.duration_ms)}</td>
                  <td className="text-xs text-gray-500">{e.source}</td></tr>))}</Table>
            )}
          </div>
        );
      })}
    </div>
  );
}
