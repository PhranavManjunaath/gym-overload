import { ArrowRight, ChevronDown, History, ShieldCheck } from "lucide-react";
import type { RecommendationOk, SessionSummary } from "@/lib/api";
import { day, kg, num, repList, rpeLine, ruleLabel, setsLine, titleCase } from "@/lib/format";
import { cn } from "@/lib/cn";
import { ButtonLink } from "@/components/ui/button";
import { Badge, Card } from "@/components/ui/surface";

/** Target line, e.g. "3 sets · 6, 6, 6 reps". Counts come straight from target_reps. */
function TargetReps({ reps }: { reps: number[] }) {
  return (
    <span className="num">
      {reps.length} {reps.length === 1 ? "set" : "sets"} <span className="text-subtle">·</span> {repList(reps)} reps
    </span>
  );
}

function SessionRow({ s }: { s: SessionSummary }) {
  const rpe = rpeLine(s.sets);
  return (
    <li className="flex flex-col gap-0.5 py-2.5 sm:flex-row sm:items-baseline sm:justify-between sm:gap-4">
      <span className="flex items-center gap-2 text-sm text-muted num">
        {day(s.date)}
        {s.deload && <Badge tone="warning">Deload</Badge>}
      </span>
      <span className="text-sm num">
        {setsLine(s.sets)}
        {rpe && <span className="text-muted"> · {rpe}</span>}
        <span className="text-muted"> · {s.total_reps} total reps</span>
      </span>
    </li>
  );
}

/**
 * The engine's recommendation with its evidence. Everything shown here is a field
 * from tools.recommend_next / plan_first_session - nothing is derived in the browser.
 */
export function RecommendationCard({ rec, compact = false, showLogAction = true }: { rec: RecommendationOk; compact?: boolean; showLogAction?: boolean }) {
  const b = rec.based_on;
  const last = b.last_session;
  const recent = b.recent_sessions ?? (last ? [last] : []);
  const st = b.settings;

  return (
    <Card className={cn("flex flex-col", compact ? "p-5" : "p-5 sm:p-6")}>
      <div className="flex items-start justify-between gap-3">
        <h3 className={cn("font-semibold tracking-tight", compact ? "text-base" : "text-lg")}>{titleCase(rec.exercise)}</h3>
        <Badge tone={rec.rule === "reduce_weight" || rec.rule === "deload" ? "warning" : "accent"}>{ruleLabel(rec.rule)}</Badge>
      </div>

      <div className="mt-4">
        <p className="text-xs font-medium uppercase tracking-[0.08em] text-muted">Next session</p>
        <p className={cn("mt-1 font-semibold tracking-tight text-accent num", compact ? "text-3xl" : "text-4xl sm:text-[44px]")}>
          {kg(rec.next.weight_kg)}
        </p>
        <p className="mt-1 text-[15px] text-fg/90">
          <TargetReps reps={rec.next.target_reps} />
        </p>
      </div>

      <div className="mt-5 border-t border-border pt-4 text-sm">
        {last ? (
          <p className="text-muted">
            <span className="text-fg/90">Last session</span> · <span className="num">{day(last.date)}: {setsLine(last.sets)}</span>
          </p>
        ) : (
          b.starting_weight_from === "user" && <p className="text-muted">Based on the starting weight you gave.</p>
        )}
        {!compact && <p className="mt-2 leading-relaxed text-muted">{rec.rule_explained}</p>}
      </div>

      {!compact && (
        <details className="group mt-4 rounded-xl border border-border bg-bg/40 open:bg-bg/60">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-4 py-3 text-sm font-medium hover:bg-elevated/50 [&::-webkit-details-marker]:hidden">
            <span className="flex items-center gap-2">
              <ShieldCheck className="size-4 text-accent" aria-hidden />
              Evidence
            </span>
            <ChevronDown className="size-4 text-muted transition-transform duration-150 group-open:rotate-180" aria-hidden />
          </summary>
          <div className="border-t border-border px-4 pb-4 pt-3">
            <p className="text-xs text-muted">
              Rule <code className="font-mono text-fg/90">{rec.rule}</code>
              {rec.reason && <> · {rec.reason}</>}
            </p>
            {recent.length > 0 && (
              <>
                <p className="mt-4 flex items-center gap-1.5 text-xs font-medium uppercase tracking-[0.08em] text-muted">
                  <History className="size-3.5" aria-hidden /> Sessions this is based on
                </p>
                <ul className="mt-1 divide-y divide-border/70">
                  {recent.map((s) => (
                    <SessionRow key={s.date + s.total_reps} s={s} />
                  ))}
                </ul>
              </>
            )}
            <p className="mt-4 text-xs text-muted num">
              Settings: {st.rep_min}–{st.rep_max} reps · {st.target_sets} sets · +{num(st.increment_kg)} kg jumps
            </p>
          </div>
        </details>
      )}

      {showLogAction && (
        <div className={cn("mt-5 flex", compact ? "mt-auto pt-5" : "")}>
          <ButtonLink href="/log" variant={compact ? "ghost" : "secondary"} size="sm" className={compact ? "-ml-3" : ""}>
            Log this workout <ArrowRight aria-hidden />
          </ButtonLink>
        </div>
      )}
    </Card>
  );
}
