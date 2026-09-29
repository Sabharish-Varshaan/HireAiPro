import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Reads the current interview question aloud with the browser's built-in
 * speechSynthesis. The rendered text stays authoritative; speech is a local
 * convenience: no audio is generated server-side and Replay makes no request.
 */
const ENABLED_KEY = "spoken_questions_enabled";
const RATE_KEY = "speech_rate";

const read = (k: string) => { try { return localStorage.getItem(k); } catch { return null; } };
const write = (k: string, v: string) => { try { localStorage.setItem(k, v); } catch { /* private mode */ } };

export function useSpokenQuestion(questionId: string | undefined, text: string | undefined) {
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;
  const [enabled, setEnabled] = useState(() => read(ENABLED_KEY) !== "false");
  const [speaking, setSpeaking] = useState(false);
  const spokenFor = useRef<string | null>(null);
  const rate = Number(read(RATE_KEY) ?? "1") || 1;

  const cancel = useCallback(() => { if (supported) window.speechSynthesis.cancel(); setSpeaking(false); }, [supported]);

  const speak = useCallback(() => {
    if (!supported || !text) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = rate;
    u.onend = u.onerror = () => setSpeaking(false);
    setSpeaking(true);
    window.speechSynthesis.speak(u);
  }, [supported, text, rate]);

  // autoplay once per NEW question; a new question cancels the previous one
  useEffect(() => {
    if (!questionId || spokenFor.current === questionId) return;
    spokenFor.current = questionId;
    cancel();
    if (enabled) speak();
  }, [questionId, enabled, speak, cancel]);

  useEffect(() => cancel, [cancel]); // unmount

  const toggleMute = () => {
    const next = !enabled;
    setEnabled(next);
    write(ENABLED_KEY, String(next));
    if (!next) cancel();
  };

  return { supported, enabled, speaking, replay: speak, cancel, toggleMute };
}
