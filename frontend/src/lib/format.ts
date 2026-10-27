/**
 * Display formatting only - turns API numbers into text. No arithmetic on workout data.
 */
import type { SetRow } from "./api";

const thousands = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

/** 62.5 -> "62.5", 1800 -> "1,800" */
export const num = (x: number): string => thousands.format(x);

/** 62.5 -> "62.5 kg" */
export const kg = (x: number): string => `${num(x)} kg`;

/** [10, 10, 9] -> "10, 10, 9" */
export const repList = (reps: number[]): string => reps.join(", ");

/** "60 kg × 10, 10, 9" when one weight, else "60×10, 62.5×8". */
export function setsLine(sets: SetRow[]): string {
  if (!sets.length) return "no sets";
  const weights = new Set(sets.map((s) => s.weight_kg));
  if (weights.size === 1) return `${kg(sets[0].weight_kg)} × ${repList(sets.map((s) => s.reps))}`;
  return sets.map((s) => `${num(s.weight_kg)}×${s.reps}`).join(", ");
}

/** "RPE 8, 8, 9" or "" when none logged. */
export function rpeLine(sets: SetRow[]): string {
  if (!sets.some((s) => s.rpe !== null)) return "";
  return "RPE " + sets.map((s) => (s.rpe === null ? "–" : num(s.rpe))).join(", ");
}

/** "2026-10-27" -> "Tue, Oct 27" (read as a calendar date, no timezone shift). */
export function day(iso: string, withYear = false): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", {
    weekday: "short",
    month: "short",
    day: "numeric",
    ...(withYear ? { year: "numeric" } : {}),
    timeZone: "UTC",
  }).format(new Date(Date.UTC(y, m - 1, d)));
}

/** "2026-10-27" -> "Oct 27" for chart axes. */
export function shortDay(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).format(
    new Date(Date.UTC(y, m - 1, d)),
  );
}

/** Today's local date as YYYY-MM-DD (for the date picker). */
export function todayIso(): string {
  const t = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}`;
}

const RULE_LABELS: Record<string, string> = {
  increase_weight: "Increase weight",
  add_reps: "Add reps",
  repeat: "Repeat weight",
  reduce_weight: "Reduce weight",
  deload: "Deload",
  resume: "Resume",
  starting_weight: "Starting weight",
};

/** Engine rule id -> readable label. The raw id is still shown in the evidence. */
export const ruleLabel = (rule: string): string => RULE_LABELS[rule] ?? rule;

export const titleCase = (s: string): string => s.replace(/\b\w/g, (c) => c.toUpperCase());
