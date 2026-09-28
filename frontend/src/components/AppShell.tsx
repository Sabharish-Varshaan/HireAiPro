import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useAuthStore } from "../stores/authStore";

function NotificationBell() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const { data } = useQuery({ queryKey: ["notifications"], queryFn: () => api.get("/me/notifications").then((r) => r.data), refetchInterval: 15000 });
  const read = useMutation({ mutationFn: (id: string) => api.post(`/me/notifications/${id}/read`), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const readAll = useMutation({ mutationFn: () => api.post("/me/notifications/read-all"), onSuccess: () => qc.invalidateQueries({ queryKey: ["notifications"] }) });
  const unread = (data ?? []).filter((n: any) => !n.read).length;
  return (
    <div className="relative">
      <button onClick={() => setOpen(!open)} className="text-sm text-gray-700 w-full text-left px-4 py-2 hover:bg-gray-50">
        Notifications {unread > 0 && <span className="ml-1 text-xs bg-red-600 text-white rounded-full px-1.5">{unread}</span>}
      </button>
      {open && (
        <div className="absolute left-full top-0 ml-2 z-20 w-80 bg-white border border-gray-200 rounded-md shadow-lg max-h-96 overflow-auto">
          <div className="flex justify-between items-center px-3 py-2 border-b border-gray-100">
            <span className="text-xs font-semibold">Notifications</span>
            <button className="text-xs underline" onClick={() => readAll.mutate()}>Mark all read</button>
          </div>
          {(data ?? []).length === 0 && <p className="text-xs text-gray-500 p-3">Nothing yet.</p>}
          {(data ?? []).map((n: any) => (
            <div key={n.id} className={`px-3 py-2 border-b border-gray-50 text-xs ${n.read ? "text-gray-500" : "bg-blue-50"}`}>
              <p className="font-medium">{n.title}</p>
              {n.body && <p>{n.body}</p>}
              <div className="flex gap-3 mt-1">
                {n.link && <Link className="underline" to={n.link} onClick={() => { read.mutate(n.id); setOpen(false); }}>Open</Link>}
                {!n.read && <button className="underline" onClick={() => read.mutate(n.id)}>Mark read</button>}
                <span className="text-gray-400">{new Date(n.created_at).toLocaleString()}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function AppShell({ nav }: { nav: { to: string; label: string; end?: boolean }[] }) {
  const { fullName, role, logout } = useAuthStore();
  const qc = useQueryClient();
  const navigate = useNavigate();
  return (
    <div className="min-h-screen flex bg-gray-50">
      <aside className="w-56 shrink-0 border-r border-gray-200 bg-white flex flex-col">
        <div className="px-4 py-4 border-b border-gray-200">
          <p className="font-semibold text-gray-900 text-sm">HireAiPro</p>
          <p className="text-xs text-gray-500 mt-0.5">{role?.replaceAll("_", " ")}</p>
        </div>
        <nav className="flex-1 py-2">
          {nav.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end ?? true}
              className={({ isActive }) => `block px-4 py-2 text-sm ${isActive ? "bg-gray-100 text-gray-900 font-medium" : "text-gray-600 hover:bg-gray-50"}`}>
              {n.label}
            </NavLink>
          ))}
          <NotificationBell />
        </nav>
        <div className="px-4 py-3 border-t border-gray-200 text-xs text-gray-500">
          <p className="truncate">{fullName}</p>
          <button onClick={() => { logout(); qc.clear(); navigate("/login"); }} className="mt-1 text-red-600 hover:underline">Sign out</button>
        </div>
      </aside>
      <main className="flex-1 min-w-0 p-6 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
