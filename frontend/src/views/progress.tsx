"use client";

import { Suspense, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Dumbbell, PenLine } from "lucide-react";
import { api, type RecommendationOk } from "@/lib/api";
import { day, kg, num, titleCase } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { ButtonLink } from "@/components/ui/button";
import { Field, Segmented, Select } from "@/components/ui/form";
import { Alert, Badge, Card, EmptyState, LoadError, PageHeader, Section, Skeleton } from "@/components/ui/surface";
import { ProgressChart } from "@/components/workout/progress-chart";
import { RecommendationCard } from "@/components/workout/recommendation-card";

type Range = "5" | "10" | "all";
const RANGES: { value: Range; label: string }[] = [
  { value: "5", label: "Last 5" },
  { value: "10", label: "Last 10" },
  { value: "all", label: "All" },
];

function Metric({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="p-4 sm:p-5">
      <p className="text-[13px] text-muted">{label}</p>
      <p className="mt-1.5 text-2xl font-semibold tracking-tight num">{value}</p>
      {hint && <p className="mt-1 text-xs text-subtle">{hint}</p>}
    </Card>
  );
}

function ExerciseProgress({ exercise, range }: { exercise: string; range: Range }) {
  const lastN = range === "all" ? undefined : Number(range);
  const progress = useApi(() => api.progress(exercise, lastN), [exercise, lastN]);
  const rec = useApi(() => api.exerciseNext(exercise), [exercise]);

  if (progress.error) return <LoadError message={progress.error} onRetry={progress.reload} />;
  if (!progress.data) {
    return (
      <div className="flex flex-col gap-4" aria-busy="true" aria-label="Loading">
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-24 rounded-card" />)}
        </div>
        <Skeleton className="h-72 rounded-card" />
      </div>
    );
  }
  if (progress.data.status !== "ok") return <Alert tone="warning">{progress.data.message}</Alert>;

  const sessions = progress.data.sessions;
  const last = sessions.at(-1);

  return (
    <>
      <Section title="Recommendation">
        {rec.data?.status === "ok" ? (
          <RecommendationCard rec={rec.data as RecommendationOk} />
        ) : rec.data ? (
          <Alert tone="info">{rec.data.message}</Alert>
        ) : (
          <Skeleton className="h-40 rounded-card" />
        )}
      </Section>

      {!last ? (
        <EmptyState
          icon={<PenLine />}
          title="No sessions logged yet"
          description={`Log a ${exercise} session to see your progress here.`}
          actions={<ButtonLink href="/log" variant="primary">Log workout</ButtonLink>}
        />
      ) : (
        <>
          <Section title={`History · latest ${day(last.date)}`}>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Metric label="Working weight" value={kg(last.working_weight_kg)} />
              <Metric label="Total reps" value={String(last.total_reps)} />
              <Metric label="Volume" value={kg(last.volume_kg)} />
              <Metric label="Est. 1RM (Epley)" value={kg(last.best_e1rm_kg)} hint="For tracking only" />
            </div>
          </Section>

          <div className="mb-10 grid gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <h3 className="font-medium">Working weight <span className="text-muted">(kg)</span></h3>
              <div className="mt-4"><ProgressChart data={sessions} metric="working_weight_kg" /></div>
            </Card>
            <Card className="p-5">
              <h3 className="font-medium">Estimated 1RM <span className="text-muted">(kg)</span></h3>
              <div className="mt-4"><ProgressChart data={sessions} metric="best_e1rm_kg" /></div>
              <p className="mt-3 text-xs text-muted">e1RM is for tracking progress only - it never picks your next weight.</p>
            </Card>
            <Card className="p-5 lg:col-span-2">
              <h3 className="font-medium">Volume per session <span className="text-muted">(kg)</span></h3>
              <div className="mt-4"><ProgressChart data={sessions} metric="volume_kg" kind="bar" /></div>
            </Card>
          </div>

          <Section title="Sessions">
            <Card className="overflow-hidden">
              {/* Table on wider screens, stacked rows on phones */}
              <table className="hidden w-full text-sm num sm:table">
                <thead>
                  <tr className="border-b border-border text-left text-xs text-muted">
                    {["Date", "Weight", "Total reps", "Volume", "e1RM", ""].map((h, i) => (
                      <th key={i} scope="col" className={`px-5 py-3 font-medium ${i > 0 && i < 5 ? "text-right" : ""}`}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {[...sessions].reverse().map((s) => (
                    <tr key={s.date + s.total_reps} className="border-b border-border/60 last:border-0 hover:bg-elevated/40">
                      <td className="px-5 py-3 text-muted">{day(s.date, true)}</td>
                      <td className="px-5 py-3 text-right">{kg(s.working_weight_kg)}</td>
                      <td className="px-5 py-3 text-right">{s.total_reps}</td>
                      <td className="px-5 py-3 text-right">{kg(s.volume_kg)}</td>
                      <td className="px-5 py-3 text-right">{kg(s.best_e1rm_kg)}</td>
                      <td className="px-5 py-3 text-right">{s.deload && <Badge tone="warning">Deload</Badge>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <ul className="divide-y divide-border sm:hidden">
                {[...sessions].reverse().map((s) => (
                  <li key={s.date + s.total_reps} className="flex items-center justify-between gap-3 px-4 py-3 num">
                    <div>
                      <p className="text-sm">{day(s.date, true)}</p>
                      <p className="text-[13px] text-muted">{s.total_reps} reps · {num(s.volume_kg)} kg vol.</p>
                    </div>
                    <div className="flex items-center gap-2">
                      {s.deload && <Badge tone="warning">Deload</Badge>}
                      <span className="font-medium">{kg(s.working_weight_kg)}</span>
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          </Section>
        </>
      )}
    </>
  );
}

function ProgressInner() {
  const params = useSearchParams();
  const exercises = useApi(() => api.exercises());
  const [picked, setChoice] = useState<string>("");
  const [range, setRange] = useState<Range>("10");

  const list = useMemo(() => exercises.data?.exercises ?? [], [exercises.data]);
  // The picked exercise, else the one in ?exercise=, else the first.
  const wanted = params.get("exercise");
  const choice =
    (picked && list.some((e) => e.exercise === picked) ? picked : list.find((e) => e.exercise === wanted)?.exercise) ??
    list[0]?.exercise ??
    "";

  return (
    <>
      <PageHeader title="Progress" description="Your logged history for one exercise. Charts show what happened; the recommendation shows what's next." />
      {exercises.error && <LoadError message={exercises.error} onRetry={exercises.reload} />}
      {exercises.loading && !exercises.data && <Skeleton className="h-11 w-64" />}
      {exercises.data && list.length === 0 && (
        <EmptyState
          icon={<Dumbbell />}
          title="No exercises yet"
          description="Add an exercise and log a session to see charts here."
          actions={<ButtonLink href="/exercises" variant="primary">Add exercise</ButtonLink>}
        />
      )}
      {list.length > 0 && choice && (
        <>
          <div className="mb-8 flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
            <Field label="Exercise" htmlFor="exercise" className="sm:w-72">
              <Select id="exercise" value={choice} onChange={(e) => setChoice(e.target.value)}>
                {list.map((e) => (
                  <option key={e.exercise} value={e.exercise}>{titleCase(e.exercise)}</option>
                ))}
              </Select>
            </Field>
            <Segmented label="Sessions shown" value={range} options={RANGES} onChange={setRange} />
          </div>
          <ExerciseProgress key={choice} exercise={choice} range={range} />
        </>
      )}
    </>
  );
}

export function ProgressView() {
  return (
    <Suspense fallback={<Skeleton className="h-11 w-64" />}>
      <ProgressInner />
    </Suspense>
  );
}
