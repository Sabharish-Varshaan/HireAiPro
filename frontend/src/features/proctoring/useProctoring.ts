import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../../api/client";
import { apiError } from "../../components/ui";

/**
 * Objective proctoring for one assessment/interview (docs/PROCTORING.md).
 *
 * - ONE getUserMedia stream per session (never re-acquired per heartbeat), released on
 *   completion/unmount so the camera light turns off.
 * - Records browser facts only: fullscreen, tab visibility, window focus, network,
 *   camera/mic track state, sustained absence of microphone signal. No recording,
 *   no face/gaze/emotion analysis, no scoring.
 * - Events are debounced client-side, batched every 5 s, and deduplicated again on the
 *   server. Heartbeat gaps are detected by the SERVER.
 */

export type Phase = "loading" | "consent" | "check" | "ready" | "active" | "completed" | "error";
export type Checks = {
  camera: boolean; microphone: boolean; audio_signal: boolean; network: boolean;
  fullscreen_capable: boolean; browser: boolean; network_latency_ms?: number | null;
};
type QueuedEvent = { event_type: string; occurred_at: string; duration_ms?: number; metadata?: Record<string, unknown> };

const DEBOUNCE_MS = 1500;
const FLUSH_MS = 5000;
const SIGNAL_THRESHOLD = 0.01; // RMS; ambient noise on a live mic is normally above this
const NO_SIGNAL_AFTER_MS = 60_000; // silence is not suspicious; only a dead input is reported

// StrictMode mounts effects twice; share one in-flight create so only one session exists
const inflight = new Map<string, Promise<any>>();
const openSession = (application_id: string, kind: string) => {
  const key = `${application_id}:${kind}`;
  if (!inflight.has(key)) {
    const p = api.post("/proctoring/sessions", { application_id, kind }).then((r) => r.data)
      .finally(() => window.setTimeout(() => inflight.delete(key), 1000));
    inflight.set(key, p);
  }
  return inflight.get(key)!;
};

export function useProctoring(applicationId: string, kind: "ASSESSMENT" | "INTERVIEW") {
  const [phase, setPhase] = useState<Phase>("loading");
  const [session, setSession] = useState<any>(null);
  const [checks, setChecks] = useState<Checks | null>(null);
  const [level, setLevel] = useState(0);
  const [warnings, setWarnings] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const stream = useRef<MediaStream | null>(null);
  const audioCtx = useRef<AudioContext | null>(null);
  const analyser = useRef<AnalyserNode | null>(null);
  const queue = useRef<QueuedEvent[]>([]);
  const lastSent = useRef<Record<string, number>>({});
  const since = useRef<Record<string, number>>({});
  const timers = useRef<number[]>([]);
  const cleanups = useRef<(() => void)[]>([]);
  const heartbeatPausedUntil = useRef(0);
  const peak = useRef(0);

  // ---------- helpers ----------
  const record = useCallback((event_type: string, extra: Partial<QueuedEvent> = {}) => {
    const now = Date.now();
    if (now - (lastSent.current[event_type] ?? 0) < DEBOUNCE_MS) return; // collapse bursts
    lastSent.current[event_type] = now;
    queue.current.push({ event_type, occurred_at: new Date(now).toISOString(), ...extra });
  }, []);

  const flush = useCallback(async () => {
    if (!session?.id || queue.current.length === 0) return;
    const batch = queue.current.splice(0, 50);
    try {
      await api.post(`/proctoring/sessions/${session.id}/events`, { events: batch });
    } catch {
      queue.current.unshift(...batch); // offline: keep and retry on the next flush
    }
  }, [session?.id]);

  const rms = () => {
    if (!analyser.current) return 0;
    const buf = new Float32Array(analyser.current.fftSize);
    analyser.current.getFloatTimeDomainData(buf);
    let s = 0;
    for (const v of buf) s += v * v;
    return Math.sqrt(s / buf.length);
  };

  const release = useCallback(() => {
    timers.current.forEach((t) => window.clearInterval(t));
    timers.current = [];
    cleanups.current.forEach((f) => f());
    cleanups.current = [];
    stream.current?.getTracks().forEach((t) => t.stop()); // camera light off
    stream.current = null;
    audioCtx.current?.close().catch(() => undefined);
    audioCtx.current = null;
    analyser.current = null;
  }, []);

  // ---------- session ----------
  useEffect(() => {
    let alive = true;
    openSession(applicationId, kind)
      .then((d) => { if (alive) { setSession(d); setPhase(d.consented ? "check" : "consent"); } })
      .catch((e) => { if (alive) { setError(e?.response ? apiError(e) : "Could not create proctoring session"); setPhase("error"); } });
    return () => { alive = false; release(); };
  }, [applicationId, kind, release]);

  const consent = async () => {
    const r = await api.post(`/proctoring/sessions/${session.id}/consent`);
    setSession(r.data);
    setPhase("check");
  };

  /** Real device checks. Permission prompts appear here, not before consent. */
  const runSystemCheck = async (videoEl: HTMLVideoElement | null) => {
    setError(null);
    const browser = typeof navigator.mediaDevices?.getUserMedia === "function" && typeof window.AudioContext === "function"
      && typeof document.documentElement.requestFullscreen === "function";
    let camera = false, microphone = false;
    try {
      if (!stream.current) {
        stream.current = await navigator.mediaDevices.getUserMedia({ video: true, audio: true });
      }
      const v = stream.current.getVideoTracks()[0];
      const a = stream.current.getAudioTracks()[0];
      camera = !!v && v.readyState === "live";
      microphone = !!a && a.readyState === "live";
      if (videoEl) { videoEl.srcObject = stream.current; await videoEl.play().catch(() => undefined); }
      if (microphone && !audioCtx.current) {
        audioCtx.current = new AudioContext();
        analyser.current = audioCtx.current.createAnalyser();
        analyser.current.fftSize = 1024;
        audioCtx.current.createMediaStreamSource(stream.current).connect(analyser.current);
      }
    } catch (e: any) {
      setError(`Camera/microphone unavailable: ${e?.name ?? "error"} ${e?.message ?? ""}`.trim());
    }
    // ~4 s of audio sampling: speak or make a sound; any live input clears the threshold
    peak.current = 0;
    await new Promise<void>((resolve) => {
      let n = 0;
      const t = window.setInterval(() => {
        const r = rms();
        peak.current = Math.max(peak.current, r);
        setLevel(r);
        if (++n >= 16) { window.clearInterval(t); resolve(); }
      }, 250);
    });
    // connectivity = browser flag + authenticated round-trip to the backend
    let network = false, latency: number | null = null;
    if (navigator.onLine) {
      const t0 = performance.now();
      try { await api.get("/proctoring/policy"); network = true; latency = Math.round(performance.now() - t0); } catch { network = false; }
    }
    const result: Checks = {
      camera, microphone, audio_signal: peak.current >= SIGNAL_THRESHOLD, network, network_latency_ms: latency,
      fullscreen_capable: !!document.fullscreenEnabled, browser,
    };
    setChecks(result);
    const passed = Object.entries(result).every(([k, v]) => k === "network_latency_ms" || v === true);
    const r = await api.post(`/proctoring/sessions/${session.id}/preflight`, { passed, checks: result });
    setSession(r.data);
    setPhase(r.data.preflight_status === "PASSED" ? "ready" : "check");
    return r.data;
  };

  // ---------- monitoring ----------
  const startMonitoring = useCallback(() => {
    const on = (target: EventTarget, name: string, fn: EventListener) => {
      target.addEventListener(name, fn);
      cleanups.current.push(() => target.removeEventListener(name, fn));
    };
    const warn = (k: string, v: boolean) => setWarnings((w) => ({ ...w, [k]: v }));

    on(document, "fullscreenchange", () => {
      if (document.fullscreenElement) { record("FULLSCREEN_ENTERED"); warn("fullscreen", false); }
      else { record("FULLSCREEN_EXITED"); warn("fullscreen", true); }
    });
    on(document, "visibilitychange", () => {
      if (document.visibilityState === "hidden") { since.current.hidden = Date.now(); record("TAB_HIDDEN"); }
      else { record("TAB_VISIBLE", { duration_ms: since.current.hidden ? Date.now() - since.current.hidden : undefined }); }
    });
    on(window, "blur", () => { since.current.blur = Date.now(); record("WINDOW_BLUR"); });
    on(window, "focus", () => record("WINDOW_FOCUS", { duration_ms: since.current.blur ? Date.now() - since.current.blur : undefined }));
    on(window, "offline", () => { since.current.offline = Date.now(); record("NETWORK_OFFLINE"); warn("offline", true); });
    on(window, "online", () => {
      record("NETWORK_ONLINE", { duration_ms: since.current.offline ? Date.now() - since.current.offline : undefined });
      warn("offline", false);
      void flush();
    });

    const tracks: [MediaStreamTrack | undefined, string, string][] = [
      [stream.current?.getVideoTracks()[0], "CAMERA", "camera"], [stream.current?.getAudioTracks()[0], "MIC", "mic"]];
    for (const [track, prefix, key] of tracks) {
      if (!track) continue;
      record(`${prefix}_STARTED`);
      track.onended = () => { record(`${prefix}_TRACK_ENDED`); warn(key, true); };
      track.onmute = () => { record(`${prefix}_MUTED`); warn(key, true); };
      track.onunmute = () => { record(`${prefix}_UNMUTED`); warn(key, false); };
      cleanups.current.push(() => { track.onended = track.onmute = track.onunmute = null; });
    }

    // sustained dead microphone input (not silence of a normal room) -> one event
    let quietSince = Date.now(), reported = false;
    timers.current.push(window.setInterval(() => {
      const r = rms();
      setLevel(r);
      if (r >= SIGNAL_THRESHOLD) { quietSince = Date.now(); reported = false; return; }
      if (!reported && Date.now() - quietSince > NO_SIGNAL_AFTER_MS) {
        record("MIC_NO_SIGNAL", { metadata: { silent_seconds: Math.round((Date.now() - quietSince) / 1000) } });
        reported = true;
      }
    }, 1000));

    const hbMs = (session?.heartbeat_seconds ?? 7) * 1000;
    timers.current.push(window.setInterval(() => {
      if (Date.now() < heartbeatPausedUntil.current) return; // test hook: simulate a dead client
      api.post(`/proctoring/sessions/${session.id}/heartbeat`).catch(() => undefined);
    }, hbMs));
    timers.current.push(window.setInterval(() => void flush(), FLUSH_MS));

    if (import.meta.env.DEV) {
      // Controlled QA hook (development builds only): stop sending heartbeats for `ms`.
      (window as any).__proctorTest = { pauseHeartbeat: (ms: number) => { heartbeatPausedUntil.current = Date.now() + ms; } };
    }
  }, [flush, record, session]);

  const start = async () => {
    setError(null);
    if (session.fullscreen_required) {
      // some embedded browsers never settle the request; do not hang the Start button
      const timeout = new Promise((_, reject) => window.setTimeout(() => reject(new Error("timeout")), 5000));
      try { await Promise.race([document.documentElement.requestFullscreen(), timeout]); }
      catch { setError("Fullscreen could not be entered. Allow fullscreen for this site (or use a regular browser window) and try again."); return; }
    }
    const r = await api.post(`/proctoring/sessions/${session.id}/start`);
    setSession(r.data);
    startMonitoring();
    setPhase("active");
  };

  const returnToFullscreen = () => document.documentElement.requestFullscreen().catch(() => undefined);

  const complete = useCallback(async () => {
    await flush();
    if (session?.id) await api.post(`/proctoring/sessions/${session.id}/complete`).catch(() => undefined);
    release();
    if (document.fullscreenElement) await document.exitFullscreen().catch(() => undefined);
    setPhase("completed");
  }, [flush, release, session?.id]);

  return { phase, session, checks, level, warnings, error, consent, runSystemCheck, start, complete, returnToFullscreen, stream };
}
