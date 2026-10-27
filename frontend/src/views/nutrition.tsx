"use client";

import { useState } from "react";
import { Check, Pencil, Plus, Utensils } from "lucide-react";
import { api, type Meal, type MealResult, type ProteinDay } from "@/lib/api";
import { day, num } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Badge, Card, LoadError, PageHeader, Section, Skeleton } from "@/components/ui/surface";

function Totals({ d }: { d: ProteinDay }) {
  return (
    <Card className="p-5 sm:p-6">
      <p className="text-[13px] text-muted">Protein today · {day(d.date)}</p>
      <p className="mt-1.5 text-4xl font-semibold tracking-tight num">
        {num(d.total_protein_g)} <span className="text-xl text-muted">g</span>
      </p>
      <p className="mt-2 text-sm text-muted num">
        {d.target_g ? (
          <>of your {num(d.target_g)} g target · <span className="text-fg/90">{num(d.remaining_g ?? 0)} g to go</span></>
        ) : (
          "No target set - add your own below."
        )}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {d.any_estimated && <Badge>Includes estimates</Badge>}
        {d.meals_missing_protein > 0 && <Badge tone="warning">{d.meals_missing_protein} meal(s) without a number</Badge>}
      </div>
    </Card>
  );
}

function MealRow({ meal, onFixed }: { meal: Meal; onFixed: () => void }) {
  const [editing, setEditing] = useState(meal.protein_g === null);
  const [grams, setGrams] = useState(meal.protein_g === null ? "" : String(meal.protein_g));
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const id = `meal-${meal.id}`;

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const r = await api.fixMeal(meal.id, Number(grams));
      if (r.status === "ok") {
        setEditing(false);
        onFixed();
      } else setError(r.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <li className="flex flex-col gap-3 px-4 py-3.5 sm:flex-row sm:items-center sm:justify-between sm:px-5">
      <div className="min-w-0">
        <p className="text-[15px]">{meal.text}</p>
        <p className="mt-0.5 text-[13px] text-muted num">
          Meal {meal.id} ·{" "}
          {meal.protein_g === null ? (
            <span className="text-warning">protein unknown</span>
          ) : (
            <>
              {num(meal.protein_g)} g protein {meal.protein_estimated ? "(estimated)" : "(your number)"}
            </>
          )}
        </p>
        {error && <p className="mt-1 text-[13px] text-danger">{error}</p>}
      </div>
      {editing ? (
        <form onSubmit={save} className="flex items-end gap-2">
          <label htmlFor={id} className="sr-only">Protein grams for meal {meal.id}</label>
          <Input id={id} type="number" inputMode="decimal" min={0} step={1} placeholder="g" className="w-24"
                 value={grams} onChange={(e) => setGrams(e.target.value)} />
          <Button type="submit" variant="primary" size="sm" loading={saving} disabled={grams === ""} icon={<Check aria-hidden />}>
            Save
          </Button>
        </form>
      ) : (
        <Button variant="ghost" size="sm" icon={<Pencil aria-hidden />} onClick={() => setEditing(true)}>
          Correct
        </Button>
      )}
    </li>
  );
}

function TargetForm({ current, onSaved }: { current: number | null; onSaved: () => void }) {
  const [value, setValue] = useState(current ? String(current) : "");
  const [msg, setMsg] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const [saving, setSaving] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      const r = await api.saveSettings({ protein_target_g: Number(value) });
      setMsg(r.status === "ok" ? { tone: "success", text: "Target saved." } : { tone: "error", text: r.message });
      if (r.status === "ok") onSaved();
    } catch (err) {
      setMsg({ tone: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <form onSubmit={save} className="flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Daily protein target (g)" htmlFor="protein-target" hint="Your own number - tracking only, no diet advice." className="flex-1">
          <Input id="protein-target" type="number" inputMode="numeric" min={1} max={500} value={value} onChange={(e) => setValue(e.target.value)} />
        </Field>
        <Button type="submit" loading={saving} disabled={!value}>Save target</Button>
      </form>
      {msg && <Alert tone={msg.tone} className="mt-3">{msg.text}</Alert>}
    </Card>
  );
}

export function NutritionView() {
  const { data, error, loading, reload } = useApi(() => api.meals());
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [result, setResult] = useState<MealResult | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  async function addMeal(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaveError(null);
    try {
      const r = await api.addMeal(text);
      if (r.status === "ok") {
        setResult(r);
        setText("");
        reload();
      } else setSaveError(r.message);
    } catch (err) {
      setSaveError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Nutrition"
        description="Track protein against your own target. Estimates come from a fixed food table in Python and are labelled - correct any of them."
      />

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="flex flex-col gap-6">
          <Card className="p-5 sm:p-6">
            <form onSubmit={addMeal} className="flex flex-col gap-3">
              <Field label="Log a meal" htmlFor="meal-text" hint="e.g. chicken breast 200g, rice 150g · 2 eggs + 1 scoop whey · or add your own '35g protein'">
                <Input id="meal-text" value={text} onChange={(e) => setText(e.target.value)} placeholder="chicken breast 200g, 2 eggs" autoComplete="off" />
              </Field>
              <Button type="submit" variant="primary" icon={<Plus aria-hidden />} loading={saving} disabled={!text.trim()} className="sm:self-start">
                Add meal
              </Button>
            </form>
            {saveError && <Alert tone="error" className="mt-4">{saveError}</Alert>}
            {result && (
              <Alert tone={result.meal.protein_g === null ? "warning" : "success"} className="mt-4"
                     title={result.meal.protein_g === null ? "Saved - protein unknown" : `Saved - ${num(result.meal.protein_g)} g protein (estimated)`}>
                {result.message ?? (
                  <span className="num">{result.breakdown.map((b) => `${b.food} ${b.amount}: ${num(b.protein_g)} g`).join(" · ")}</span>
                )}
              </Alert>
            )}
          </Card>

          <Section title="Today's meals" className="mb-0">
            {error && <LoadError message={error} onRetry={reload} />}
            {loading && !data && <Skeleton className="h-32 rounded-card" />}
            {data && data.meals.length === 0 && (
              <Card className="flex flex-col items-center px-6 py-10 text-center">
                <Utensils className="mb-3 size-6 text-accent" aria-hidden />
                <p className="font-medium">No meals logged today.</p>
              </Card>
            )}
            {data && data.meals.length > 0 && (
              <Card>
                <ul className="divide-y divide-border">
                  {data.meals.map((m) => <MealRow key={`${m.id}-${m.protein_g}`} meal={m} onFixed={reload} />)}
                </ul>
              </Card>
            )}
          </Section>
        </div>

        <div className="flex flex-col gap-6">
          {data ? <Totals d={data} /> : <Skeleton className="h-40 rounded-card" />}
          {data && <TargetForm key={data.target_g ?? "none"} current={data.target_g} onSaved={reload} />}
        </div>
      </div>
    </>
  );
}
