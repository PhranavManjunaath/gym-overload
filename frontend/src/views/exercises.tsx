"use client";

import Link from "next/link";
import { useState } from "react";
import { Dumbbell, Plus, Search, Target, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import { num, titleCase } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/form";
import { Alert, Badge, Card, LoadError, PageHeader, Skeleton } from "@/components/ui/surface";

const EQUIPMENT = ["barbell", "dumbbell", "machine", "cable", "other"];

function AddExerciseForm({ onAdded }: { onAdded: (name: string) => void }) {
  const meta = useApi(() => api.meta());
  const [name, setName] = useState("");
  const [equipment, setEquipment] = useState("barbell");
  const [repMin, setRepMin] = useState("");
  const [repMax, setRepMax] = useState("");
  const [sets, setSets] = useState("");
  const [jump, setJump] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const d = meta.data?.defaults;
  const jumps = meta.data
    ? Object.entries(meta.data.default_increments_kg).map(([k, v]) => `${k} +${num(v)} kg`).join(", ")
    : "";
  const optional = (v: string) => (v.trim() === "" ? undefined : Number(v));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const r = await api.addExercise({
        name,
        equipment,
        rep_min: optional(repMin),
        rep_max: optional(repMax),
        target_sets: optional(sets),
        increment_kg: optional(jump) ?? null,
      });
      if (r.status === "ok") {
        onAdded(r.exercise);
        setName("");
        setRepMin("");
        setRepMax("");
        setSets("");
        setJump("");
      } else {
        setError(r.message);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <h2 className="font-semibold">Add exercise</h2>
      <p className="mt-1 text-sm text-muted">Empty fields use the defaults.</p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-4">
        <Field label="Name" htmlFor="ex-name">
          <Input id="ex-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="bench press" autoComplete="off" required />
        </Field>
        <Field label="Equipment" htmlFor="ex-equipment">
          <Select id="ex-equipment" value={equipment} onChange={(e) => setEquipment(e.target.value)}>
            {EQUIPMENT.map((x) => <option key={x} value={x}>{titleCase(x)}</option>)}
          </Select>
        </Field>
        <div className="grid grid-cols-3 gap-3">
          <Field label="Min reps" htmlFor="ex-min">
            <Input id="ex-min" type="number" inputMode="numeric" min={1} step={1} value={repMin} onChange={(e) => setRepMin(e.target.value)} placeholder={d ? String(d.rep_min) : ""} />
          </Field>
          <Field label="Max reps" htmlFor="ex-max">
            <Input id="ex-max" type="number" inputMode="numeric" min={1} step={1} value={repMax} onChange={(e) => setRepMax(e.target.value)} placeholder={d ? String(d.rep_max) : ""} />
          </Field>
          <Field label="Sets" htmlFor="ex-sets">
            <Input id="ex-sets" type="number" inputMode="numeric" min={1} step={1} value={sets} onChange={(e) => setSets(e.target.value)} placeholder={d ? String(d.target_sets) : ""} />
          </Field>
        </div>
        <Field
          label="Weight jump (kg)"
          htmlFor="ex-jump"
          hint={`Leave empty for the default (${jumps}). Required for other equipment.`}
        >
          <Input id="ex-jump" type="number" inputMode="decimal" min={0} step={0.5} value={jump} onChange={(e) => setJump(e.target.value)} />
        </Field>
        {error && <Alert tone="error">{error}</Alert>}
        <Button type="submit" variant="primary" icon={<Plus aria-hidden />} loading={saving} disabled={!name.trim()}>
          Add exercise
        </Button>
      </form>
    </Card>
  );
}

export function ExercisesView() {
  const { data, error, loading, reload } = useApi(() => api.exercises());
  const [query, setQuery] = useState("");
  const [added, setAdded] = useState<string | null>(null);
  const list = (data?.exercises ?? []).filter((e) => e.exercise.includes(query.trim().toLowerCase()));

  return (
    <>
      <PageHeader title="Exercises" description="Your lifts and their progression settings." />
      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-4">
          {added && <Alert tone="success">Added {added}.</Alert>}
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
            <Input aria-label="Search exercises" placeholder="Search exercises" value={query} onChange={(e) => setQuery(e.target.value)} className="pl-9" />
          </div>
          {error && <LoadError message={error} onRetry={reload} />}
          {loading && !data && [0, 1, 2].map((i) => <Skeleton key={i} className="h-20 rounded-card" />)}
          {data && data.exercises.length === 0 && (
            <Card className="flex flex-col items-center px-6 py-12 text-center">
              <div className="mb-4 grid size-11 place-items-center rounded-xl border border-border bg-elevated text-accent">
                <Dumbbell className="size-5" aria-hidden />
              </div>
              <p className="font-medium">No exercises yet - add your first one.</p>
              <p className="mt-1 text-sm text-muted">Then log a session to get your first recommendation.</p>
            </Card>
          )}
          {data && data.exercises.length > 0 && list.length === 0 && (
            <p className="py-6 text-center text-sm text-muted">No exercises match “{query}”.</p>
          )}
          {list.map((e) => (
            <Card key={e.exercise} className="flex flex-col gap-4 p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="truncate font-medium">{titleCase(e.exercise)}</h3>
                  <Badge>{e.equipment}</Badge>
                </div>
                <p className="mt-1 text-sm text-muted num">
                  {e.settings.rep_min}–{e.settings.rep_max} reps · {e.settings.target_sets} sets · +{num(e.settings.increment_kg)} kg jumps
                </p>
              </div>
              <div className="flex gap-1">
                <Link href={`/progress?exercise=${encodeURIComponent(e.exercise)}`} className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-muted hover:bg-elevated hover:text-fg">
                  <TrendingUp className="size-4" aria-hidden /> Progress
                </Link>
                <Link href="/next" className="inline-flex h-8 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium text-muted hover:bg-elevated hover:text-fg">
                  <Target className="size-4" aria-hidden /> Next
                </Link>
              </div>
            </Card>
          ))}
        </div>
        <AddExerciseForm
          onAdded={(name) => {
            setAdded(name);
            reload();
          }}
        />
      </div>
    </>
  );
}
