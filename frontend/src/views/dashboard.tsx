"use client";

import Link from "next/link";
import { ArrowRight, Dumbbell, PenLine, Target } from "lucide-react";
import { api, type RecommendationOk, type RecentSession } from "@/lib/api";
import { day, kg, num, titleCase } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { ButtonLink } from "@/components/ui/button";
import { Badge, Card, EmptyState, LoadError, PageHeader, Section, Skeleton } from "@/components/ui/surface";
import { RecommendationCard } from "@/components/workout/recommendation-card";

function RecentList({ sessions }: { sessions: RecentSession[] }) {
  return (
    <Card className="divide-y divide-border">
      {sessions.map((s) => (
        <Link
          key={`${s.date}-${s.exercise}`}
          href={`/progress?exercise=${encodeURIComponent(s.exercise)}`}
          className="flex items-center gap-4 px-4 py-3.5 transition-colors duration-150 first:rounded-t-card last:rounded-b-card hover:bg-elevated/50 sm:px-5"
        >
          <div className="w-24 shrink-0 text-sm text-muted num">{day(s.date)}</div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium">{titleCase(s.exercise)}</p>
            <p className="text-[13px] text-muted num sm:hidden">
              {kg(s.working_weight_kg)} · {s.total_reps} reps
            </p>
          </div>
          <div className="hidden items-center gap-6 text-sm num sm:flex">
            <span>{kg(s.working_weight_kg)}</span>
            <span className="w-16 text-right text-muted">{s.total_reps} reps</span>
            <span className="w-28 text-right text-muted">{num(s.volume_kg)} kg vol.</span>
          </div>
          {s.deload && <Badge tone="warning">Deload</Badge>}
          <ArrowRight className="size-4 shrink-0 text-subtle" aria-hidden />
        </Link>
      ))}
    </Card>
  );
}

function DashboardSkeleton() {
  return (
    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3" aria-busy="true" aria-label="Loading">
      {[0, 1, 2].map((i) => (
        <Card key={i} className="p-5">
          <Skeleton className="h-5 w-28" />
          <Skeleton className="mt-6 h-9 w-32" />
          <Skeleton className="mt-3 h-4 w-40" />
          <Skeleton className="mt-6 h-4 w-full" />
        </Card>
      ))}
    </div>
  );
}

export function DashboardView() {
  const { data, error, loading, reload } = useApi(() => api.dashboard());
  const logAction = (
    <ButtonLink href="/log" variant="primary" icon={<PenLine aria-hidden />}>
      Log workout
    </ButtonLink>
  );

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Your next targets and recent training, straight from your logged sets."
        actions={logAction}
      />

      {loading && !data && <DashboardSkeleton />}
      {error && <LoadError message={error} onRetry={reload} />}

      {data && data.exercises.length === 0 && (
        <EmptyState
          icon={<Dumbbell />}
          title="Set up your first exercise"
          description="Add the lifts you train, then log a session. Your next targets appear here after your first workout."
          actions={
            <>
              <ButtonLink href="/exercises" variant="primary">Add exercise</ButtonLink>
              <ButtonLink href="/log">Log workout</ButtonLink>
            </>
          }
        />
      )}

      {data && data.exercises.length > 0 && (
        <>
          <Section
            title="Next session"
            action={
              <Link href="/next" className="flex items-center gap-1 text-[13px] font-medium text-muted hover:text-fg">
                All targets <ArrowRight className="size-3.5" aria-hidden />
              </Link>
            }
          >
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {data.next.map((r) =>
                r.status === "ok" ? (
                  <RecommendationCard key={r.exercise} rec={r as RecommendationOk} compact />
                ) : r.status === "need_starting_weight" ? (
                  <Card key={r.exercise} className="flex flex-col p-5">
                    <div className="flex items-start justify-between gap-3">
                      <h3 className="text-base font-semibold tracking-tight">{titleCase(r.exercise)}</h3>
                      <Badge>No history yet</Badge>
                    </div>
                    <p className="mt-3 text-sm text-muted">Choose a starting weight to plan your first session.</p>
                    <div className="mt-auto pt-5">
                      <ButtonLink href="/next" variant="ghost" size="sm" className="-ml-3" icon={<Target aria-hidden />}>
                        Set starting weight
                      </ButtonLink>
                    </div>
                  </Card>
                ) : null,
              )}
            </div>
          </Section>

          <Section title="Recent workouts">
            {data.recent.length > 0 ? (
              <RecentList sessions={data.recent} />
            ) : (
              <EmptyState
                icon={<PenLine />}
                title="No workouts logged yet"
                description="Log your first session to start progressing. Recommendations are built from what you actually lift."
                actions={logAction}
              />
            )}
          </Section>
        </>
      )}
    </>
  );
}
