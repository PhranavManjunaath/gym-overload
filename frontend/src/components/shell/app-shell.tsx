"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Dumbbell,
  LayoutDashboard,
  Menu,
  MessageSquare,
  PenLine,
  Settings,
  Target,
  TrendingUp,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { AuthGate } from "./auth-gate";

type NavItem = { href: string; label: string; icon: LucideIcon; mobileTab?: string };

const NAV: NavItem[] = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard, mobileTab: "Home" },
  { href: "/log", label: "Log workout", icon: PenLine, mobileTab: "Log" },
  { href: "/next", label: "Next session", icon: Target, mobileTab: "Next" },
  { href: "/progress", label: "Progress", icon: TrendingUp, mobileTab: "Progress" },
  { href: "/exercises", label: "Exercises", icon: Dumbbell },
  { href: "/coach", label: "AI coach", icon: MessageSquare },
  { href: "/settings", label: "Settings", icon: Settings },
];

const isActive = (pathname: string, href: string) => (href === "/" ? pathname === "/" : pathname.startsWith(href));

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5 rounded-md" aria-label="Gym Overload home">
      <span className="grid size-8 place-items-center rounded-lg bg-accent text-accent-fg">
        <Dumbbell className="size-[18px]" strokeWidth={2.25} aria-hidden />
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Gym Overload</span>
    </Link>
  );
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main" className="flex flex-col gap-0.5">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(pathname, href);
        return (
          <Link
            key={href}
            href={href}
            onNavigate={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex h-10 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors duration-150",
              active ? "bg-elevated text-fg" : "text-muted hover:bg-elevated/60 hover:text-fg",
            )}
          >
            {active && <span aria-hidden className="absolute inset-y-2 left-0 w-[3px] rounded-full bg-accent" />}
            <Icon className={cn("size-[18px]", active ? "text-accent" : "text-subtle group-hover:text-muted")} aria-hidden />
            {label}
          </Link>
        );
      })}
    </nav>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [menuOpen, setMenuOpen] = useState(false);

  // Close the mobile menu on Escape.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setMenuOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="min-h-dvh">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-64 flex-col border-r border-border bg-sidebar px-4 py-6 lg:flex">
        <div className="px-2">
          <Logo />
        </div>
        <div className="mt-8 flex-1">
          <NavLinks pathname={pathname} />
        </div>
        <p className="px-3 text-xs leading-relaxed text-subtle">
          Every number comes from the progression engine - never from the AI.
        </p>
      </aside>

      {/* Mobile top bar */}
      <header className="sticky top-0 z-30 flex h-14 items-center justify-between border-b border-border bg-bg/90 px-4 backdrop-blur lg:hidden">
        <Logo />
        <button
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
          className="grid size-10 place-items-center rounded-lg text-muted hover:bg-elevated hover:text-fg"
        >
          <Menu className="size-5" aria-hidden />
        </button>
      </header>

      {/* Mobile menu sheet */}
      {menuOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <button aria-label="Close menu" className="absolute inset-0 bg-black/60" onClick={() => setMenuOpen(false)} />
          <div className="absolute inset-x-0 top-0 rounded-b-2xl border-b border-border bg-sidebar p-4 pb-5">
            <div className="mb-4 flex items-center justify-between">
              <Logo />
              <button
                onClick={() => setMenuOpen(false)}
                aria-label="Close menu"
                className="grid size-10 place-items-center rounded-lg text-muted hover:bg-elevated hover:text-fg"
              >
                <X className="size-5" aria-hidden />
              </button>
            </div>
            <NavLinks pathname={pathname} onNavigate={() => setMenuOpen(false)} />
          </div>
        </div>
      )}

      <main className="lg:pl-64">
        <div className="mx-auto w-full max-w-6xl px-4 pb-28 pt-6 sm:px-6 lg:px-10 lg:pb-16 lg:pt-10">
          <AuthGate>{children}</AuthGate>
        </div>
      </main>

      {/* Mobile bottom tabs */}
      <nav
        aria-label="Quick"
        className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-4 border-t border-border bg-sidebar/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
      >
        {NAV.filter((n) => n.mobileTab).map(({ href, mobileTab, icon: Icon }) => {
          const active = isActive(pathname, href);
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex h-16 flex-col items-center justify-center gap-1 text-[11px] font-medium",
                active ? "text-accent" : "text-muted hover:text-fg",
              )}
            >
              <Icon className="size-5" aria-hidden />
              {mobileTab}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
