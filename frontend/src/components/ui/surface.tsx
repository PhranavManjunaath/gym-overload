import { CircleAlert, CircleCheck, Info, TriangleAlert } from "lucide-react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: ComponentProps<"div">) {
  return <div className={cn("rounded-card border border-border bg-surface", className)} {...props} />;
}

export function PageHeader({ title, description, actions }: { title: string; description?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
      <div className="min-w-0">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">{title}</h1>
        {description && <p className="mt-1.5 max-w-2xl text-[15px] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap gap-2">{actions}</div>}
    </header>
  );
}

export function Section({ title, action, children, className }: { title: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={cn("mb-10", className)}>
      <div className="mb-3 flex items-center justify-between gap-3">
        <h2 className="text-[13px] font-medium uppercase tracking-[0.08em] text-muted">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

type Tone = "accent" | "neutral" | "warning" | "success";
const tones: Record<Tone, string> = {
  accent: "border-accent/30 bg-accent/10 text-accent",
  neutral: "border-border bg-elevated text-muted",
  warning: "border-warning/30 bg-warning/10 text-warning",
  success: "border-success/30 bg-success/10 text-success",
};

export function Badge({ tone = "neutral", children, className }: { tone?: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn("inline-flex h-6 items-center gap-1 rounded-md border px-2 text-xs font-medium whitespace-nowrap", tones[tone], className)}>
      {children}
    </span>
  );
}

type AlertTone = "error" | "warning" | "success" | "info";
const alertStyles: Record<AlertTone, { box: string; icon: ReactNode }> = {
  error: { box: "border-danger/30 bg-danger/[0.08] text-danger", icon: <CircleAlert aria-hidden /> },
  warning: { box: "border-warning/30 bg-warning/[0.08] text-warning", icon: <TriangleAlert aria-hidden /> },
  success: { box: "border-success/30 bg-success/[0.08] text-success", icon: <CircleCheck aria-hidden /> },
  info: { box: "border-border bg-elevated text-muted", icon: <Info aria-hidden /> },
};

export function Alert({ tone, title, children, className }: { tone: AlertTone; title?: string; children?: ReactNode; className?: string }) {
  const s = alertStyles[tone];
  return (
    <div role={tone === "error" ? "alert" : "status"} className={cn("flex gap-3 rounded-xl border p-4 text-sm", s.box, className)}>
      <span className="mt-px shrink-0 [&_svg]:size-[18px]">{s.icon}</span>
      <div className="min-w-0 flex-1">
        {title && <p className="font-medium">{title}</p>}
        {children && <div className={cn("text-fg/85", title && "mt-1")}>{children}</div>}
      </div>
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-md bg-elevated", className)} />;
}

export function EmptyState({ icon, title, description, actions }: { icon: ReactNode; title: string; description: ReactNode; actions?: ReactNode }) {
  return (
    <Card className="flex flex-col items-center px-6 py-14 text-center">
      <div className="mb-5 grid size-12 place-items-center rounded-xl border border-border bg-elevated text-accent [&_svg]:size-6">
        {icon}
      </div>
      <h3 className="text-lg font-semibold">{title}</h3>
      <p className="mt-2 max-w-md text-[15px] text-muted">{description}</p>
      {actions && <div className="mt-6 flex flex-wrap justify-center gap-2">{actions}</div>}
    </Card>
  );
}

/** Error from the API (unreachable, failed request) with a retry. */
export function LoadError({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <Alert tone="error" title="Couldn't load this page">
      <p>{message}</p>
      {message.startsWith("Can't reach") && (
        <p className="mt-2 text-muted">
          Start it with <code className="font-mono text-fg">uvicorn api:create_app --factory --port 8000</code>
        </p>
      )}
      {onRetry && (
        <button onClick={onRetry} className="mt-3 text-sm font-medium text-fg underline underline-offset-4 hover:text-accent">
          Try again
        </button>
      )}
    </Alert>
  );
}
