import { NavLink, Outlet } from "react-router";

import { useNotifications } from "../api/hooks";
import { useAuth } from "../auth/context";

const LINKS = [
  { to: "/", label: "Dashboard", end: true },
  { to: "/accounts", label: "Accounts" },
  { to: "/transactions", label: "Transactions" },
  { to: "/budgets", label: "Budgets" },
  { to: "/banks", label: "Banks" },
];

export function Layout() {
  const { logout } = useAuth();
  const { data: unread } = useNotifications();
  return (
    <div className="min-h-dvh">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:m-2 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <header className="bg-brand-700 text-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between gap-3 px-4 py-3">
          <span className="text-lg font-bold tracking-tight">Onesum</span>
          <div className="flex items-center gap-3">
            {unread && unread.length > 0 && (
              <NavLink to="/" className="rounded-full bg-white/15 px-2.5 py-1 text-xs font-semibold">
                {unread.length} alert{unread.length > 1 ? "s" : ""}
              </NavLink>
            )}
            <button type="button" onClick={() => void logout()} className="text-sm font-medium underline-offset-4 hover:underline">
              Sign out
            </button>
          </div>
        </div>
        <nav aria-label="Main" className="mx-auto max-w-5xl overflow-x-auto px-2">
          <ul className="flex gap-1 whitespace-nowrap pb-2">
            {LINKS.map((link) => (
              <li key={link.to}>
                <NavLink
                  to={link.to}
                  end={link.end}
                  className={({ isActive }) =>
                    `block rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-white text-brand-800" : "text-white/90 hover:bg-white/10"}`
                  }
                >
                  {link.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </header>
      <main id="main" className="mx-auto max-w-5xl px-4 py-5">
        <Outlet />
      </main>
    </div>
  );
}
