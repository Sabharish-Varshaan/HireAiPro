import { NavLink, Outlet } from "react-router-dom";
import { useAuthStore } from "../stores/authStore";

export function AppShell({ nav }: { nav: { to: string; label: string }[] }) {
  const { fullName, role, logout } = useAuthStore();
  return (
    <div className="min-h-screen flex bg-gray-50">
      <aside className="w-56 border-r border-gray-200 bg-white flex flex-col">
        <div className="px-4 py-4 border-b border-gray-200">
          <p className="font-semibold text-gray-900 text-sm">HireAiPro</p>
          <p className="text-xs text-gray-500 mt-0.5">{role}</p>
        </div>
        <nav className="flex-1 py-2">
          {nav.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              className={({ isActive }) =>
                `block px-4 py-2 text-sm ${isActive ? "bg-gray-100 text-gray-900 font-medium" : "text-gray-600 hover:bg-gray-50"}`
              }
            >
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="px-4 py-3 border-t border-gray-200 text-xs text-gray-500">
          <p className="truncate">{fullName}</p>
          <button onClick={logout} className="mt-1 text-red-600 hover:underline">
            Sign out
          </button>
        </div>
      </aside>
      <main className="flex-1 p-6 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}
