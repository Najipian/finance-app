import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet } from "react-router";

import { useConnections, useMe, useNotifications } from "../api/hooks";
import { useAuth } from "../auth/context";
import { formatRelative } from "../lib/format";
import { Icon, type IconName, LogoMark } from "./icons";

const REPO_URL = "https://github.com/Najipian/finance-app";
const YEAR = new Date().getFullYear();

interface NavItem {
  to: string;
  label: string;
  /** Shorter label for the mobile tab bar. */
  short: string;
  icon: IconName;
  end?: boolean;
}

const NAV: NavItem[] = [
  { to: "/", label: "Overview", short: "Home", icon: "home", end: true },
  { to: "/accounts", label: "Accounts", short: "Accounts", icon: "wallet" },
  { to: "/transactions", label: "Transactions", short: "Activity", icon: "list" },
  { to: "/budgets", label: "Budgets", short: "Budgets", icon: "target" },
  { to: "/banks", label: "Banks", short: "Banks", icon: "bank" },
];

/** App shell: sticky header, page content, footer, and a bottom tab bar on phones. */
export function Layout() {
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:m-2 focus:rounded focus:bg-white focus:p-2">
        Skip to content
      </a>
      <Header />
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 sm:px-6">
        <Outlet />
      </main>
      <Footer />
      <TabBar />
    </div>
  );
}

function Header() {
  return (
    <header className="sticky top-0 z-30 border-b border-black/8 bg-white/90 backdrop-blur supports-[backdrop-filter]:bg-white/75">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <div className="flex h-full items-center gap-8">
          <Link to="/" className="flex items-center gap-2 rounded-md text-[15px] font-semibold tracking-tight">
            <LogoMark />
            Ovra
          </Link>
          <nav aria-label="Main" className="hidden h-full md:block">
            <ul className="flex h-full gap-6">
              {NAV.map((item) => (
                <li key={item.to} className="h-full">
                  <NavLink
                    to={item.to}
                    end={item.end}
                    className={({ isActive }) =>
                      `flex h-full items-center border-b-2 text-sm transition-colors ${
                        isActive ? "border-brand-700 font-medium text-ink" : "border-transparent text-muted hover:text-ink"
                      }`
                    }
                  >
                    {item.label}
                  </NavLink>
                </li>
              ))}
            </ul>
          </nav>
        </div>
        <div className="flex items-center gap-1 sm:gap-2">
          <SyncStatus />
          <AlertsBell />
          <AccountMenu />
        </div>
      </div>
    </header>
  );
}

/** "Synced 4 min ago" across all bank connections; links to the Banks page. */
function SyncStatus() {
  const { data: connections } = useConnections();
  if (!connections || connections.length === 0) return null;

  const failed = connections.some((c) => c.last_sync_status === "failed");
  const latest = connections
    .map((c) => c.last_synced_at)
    .filter((t): t is string => t !== null)
    .sort()
    .at(-1);
  const text = failed ? "Sync problem" : latest ? `Synced ${formatRelative(latest)}` : "Syncing…";

  return (
    <Link
      to="/banks"
      className={`flex items-center gap-1.5 rounded-full px-2 py-1.5 text-xs ring-1 sm:px-3 ${
        failed ? "text-danger ring-danger/30" : "text-muted ring-black/10 hover:text-ink"
      }`}
    >
      <Icon name={failed ? "alert" : "refresh"} className="size-4" />
      <span className="sr-only sm:not-sr-only">{text}</span>
    </Link>
  );
}

function AlertsBell() {
  const { data: unread } = useNotifications();
  const count = unread?.length ?? 0;
  return (
    <Link
      to={{ pathname: "/", hash: "alerts" }}
      className="relative rounded-full p-2 text-muted hover:bg-black/5 hover:text-ink"
      aria-label={count ? `${count} unread alert${count > 1 ? "s" : ""}` : "No unread alerts"}
    >
      <Icon name="bell" />
      {count > 0 && (
        <span className="absolute top-1 right-1 flex min-w-4 items-center justify-center rounded-full bg-danger px-1 text-[10px] leading-4 font-semibold text-white">
          {count}
        </span>
      )}
    </Link>
  );
}

function initials(email: string): string {
  const name = email.split("@")[0] ?? "";
  const parts = name.split(/[._-]+/).filter(Boolean);
  const letters = parts.length > 1 ? parts[0][0] + parts[1][0] : name.slice(0, 2);
  return letters.toUpperCase() || "?";
}

/** Avatar button with a small menu: who is signed in, and sign out. */
function AccountMenu() {
  const { logout } = useAuth();
  const { data: me } = useMe();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (event: MouseEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent ? event.key === "Escape" : !ref.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        onClick={() => setOpen(!open)}
        className="ml-1 flex size-8 items-center justify-center rounded-full bg-brand-100 text-xs font-semibold text-brand-800 hover:bg-brand-50"
      >
        {me ? initials(me.email) : ""}
      </button>
      {open && (
        <div role="menu" className="absolute right-0 mt-2 w-60 rounded-xl bg-white p-1.5 shadow-lg ring-1 ring-black/10">
          {me && (
            <p className="truncate px-3 pt-2 pb-2.5 text-sm text-muted" title={me.email}>
              Signed in as
              <span className="block truncate font-medium text-ink">{me.email}</span>
            </p>
          )}
          <button
            type="button"
            role="menuitem"
            onClick={() => void logout()}
            className="flex w-full items-center gap-2 rounded-lg px-3 py-2 text-left text-sm hover:bg-surface"
          >
            <Icon name="logout" className="size-4" />
            Sign out
          </button>
        </div>
      )}
    </div>
  );
}

const FOOTER_COLUMNS: { title: string; links: { label: string; to?: string; href?: string; icon?: IconName }[] }[] = [
  {
    title: "Product",
    links: [
      { label: "Overview", to: "/" },
      { label: "Transactions", to: "/transactions" },
      { label: "Budgets", to: "/budgets" },
      { label: "Connect a bank", to: "/banks" },
    ],
  },
  {
    title: "Trust",
    links: [
      { label: "How we protect data", href: `${REPO_URL}#security-notes`, icon: "lock" },
      { label: "Bank consent flow", href: `${REPO_URL}/blob/main/docs/adr/0003-bank-consent-flow.md` },
      { label: "Disconnect a bank", to: "/banks" },
    ],
  },
  {
    title: "Project",
    links: [
      { label: "Source code", href: REPO_URL, icon: "github" },
      { label: "API docs", href: "/docs" },
      { label: "Architecture", href: `${REPO_URL}/blob/main/docs/technical-design.md` },
    ],
  },
];

function Footer() {
  return (
    <footer className="mt-10 border-t border-black/8 bg-white pb-20 md:pb-0">
      <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-[1.6fr_1fr_1fr_1fr]">
          <div className="col-span-2 md:col-span-1">
            <p className="flex items-center gap-2 font-semibold tracking-tight">
              <LogoMark className="size-6" />
              Ovra
            </p>
            <p className="mt-3 max-w-xs text-sm text-muted">
              Every account, one overview. Read-only Open Banking: Ovra can see your balances and transactions, never move
              your money.
            </p>
          </div>
          {FOOTER_COLUMNS.map((column) => (
            <nav key={column.title} aria-label={column.title}>
              <h2 className="text-sm font-medium">{column.title}</h2>
              <ul className="mt-3 space-y-2 text-sm">
                {column.links.map((link) => {
                  const content = (
                    <>
                      {link.icon && <Icon name={link.icon} className="size-4" />}
                      {link.label}
                    </>
                  );
                  const className = "inline-flex items-center gap-1.5 text-muted hover:text-ink";
                  return (
                    <li key={link.label}>
                      {link.to ? (
                        <Link to={link.to} className={className}>
                          {content}
                        </Link>
                      ) : (
                        <a href={link.href} className={className} {...(link.href?.startsWith("http") ? { target: "_blank", rel: "noreferrer" } : {})}>
                          {content}
                        </a>
                      )}
                    </li>
                  );
                })}
              </ul>
            </nav>
          ))}
        </div>
        <div className="mt-8 flex flex-col gap-2 border-t border-black/8 pt-5 text-xs text-muted sm:flex-row sm:items-center sm:justify-between">
          <p>© {YEAR} Ovra · Portfolio project, sandbox data only</p>
          <p className="flex items-center gap-1.5">
            <Icon name="shield" className="size-4" />
            Read-only access (AIS) · v{__APP_VERSION__}
          </p>
        </div>
      </div>
    </footer>
  );
}

/** Bottom navigation on phones; the header nav takes over from the md breakpoint. */
function TabBar() {
  return (
    <nav
      aria-label="Main"
      className="fixed inset-x-0 bottom-0 z-30 border-t border-black/8 bg-white/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden"
    >
      <ul className="grid grid-cols-5">
        {NAV.map((item) => (
          <li key={item.to}>
            <NavLink
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `flex flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "font-medium text-brand-700" : "text-muted"}`
              }
            >
              <Icon name={item.icon} className="size-6" />
              {item.short}
            </NavLink>
          </li>
        ))}
      </ul>
    </nav>
  );
}
