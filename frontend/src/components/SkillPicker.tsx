import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { api } from "../api/client";
import { inputCls } from "./ui";

export function SkillPicker({ onPick }: { onPick: (s: { id: string; canonical_name: string }) => void }) {
  const [q, setQ] = useState("");
  const { data } = useQuery({
    queryKey: ["skill-search", q],
    queryFn: () => api.get("/skills", { params: { q, limit: 8 } }).then((r) => r.data),
    enabled: q.length >= 2,
  });
  return (
    <div className="relative">
      <input className={inputCls} placeholder="Search canonical skill…" value={q} onChange={(e) => setQ(e.target.value)} />
      {q.length >= 2 && data && (
        <div className="absolute z-10 bg-white border border-gray-200 rounded-md mt-1 w-full shadow-sm max-h-56 overflow-auto">
          {data.length === 0 && <p className="text-xs text-gray-500 p-2">No canonical skill matches “{q}”.</p>}
          {data.map((s: { id: string; canonical_name: string; category: string }) => (
            <button key={s.id} className="block w-full text-left text-sm px-2 py-1 hover:bg-gray-50"
              onClick={() => { onPick(s); setQ(""); }}>
              {s.canonical_name} <span className="text-xs text-gray-400">{s.category}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
