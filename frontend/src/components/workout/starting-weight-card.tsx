"use client";

import { useState } from "react";
import { api, type NeedStartingWeight, type Recommendation } from "@/lib/api";
import { num, titleCase } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Badge, Card } from "@/components/ui/surface";
import { RecommendationCard } from "./recommendation-card";

/**
 * No history yet: the user chooses the starting weight (no default value - the
 * coach never guesses). plan_first_session then returns the first session.
 */
export function StartingWeightCard({ rec }: { rec: NeedStartingWeight }) {
  const [weight, setWeight] = useState("");
  const [plan, setPlan] = useState<Recommendation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const id = `start-${rec.exercise.replace(/\s+/g, "-")}`;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const r = await api.firstSession(rec.exercise, Number(weight));
      if (r.status === "ok") setPlan(r);
      else setError(r.message);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  if (plan?.status === "ok") return <RecommendationCard rec={plan} />;

  return (
    <Card className="flex flex-col p-5 sm:p-6">
      <div className="flex items-start justify-between gap-3">
        <h3 className="text-lg font-semibold tracking-tight">{titleCase(rec.exercise)}</h3>
        <Badge>No history yet</Badge>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-muted">
        Choose your starting weight - the coach never guesses one. Your first session will aim for{" "}
        <span className="num text-fg/90">{rec.settings.rep_min}</span> reps on each of{" "}
        <span className="num text-fg/90">{rec.settings.target_sets}</span> sets.
      </p>
      <form onSubmit={submit} className="mt-5 flex flex-col gap-3 sm:flex-row sm:items-end">
        <Field label="Starting weight (kg)" htmlFor={id} className="flex-1">
          <Input
            id={id}
            type="number"
            inputMode="decimal"
            min={0}
            step={rec.settings.increment_kg}
            placeholder={`e.g. a multiple of ${num(rec.settings.increment_kg)}`}
            value={weight}
            onChange={(e) => setWeight(e.target.value)}
          />
        </Field>
        <Button type="submit" variant="primary" loading={loading} disabled={!weight || Number(weight) <= 0}>
          Plan first session
        </Button>
      </form>
      {error && <Alert tone="error" className="mt-4">{error}</Alert>}
    </Card>
  );
}
