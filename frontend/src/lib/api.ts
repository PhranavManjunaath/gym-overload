/**
 * Client for the Python API (api.py). The API is the only source of numbers:
 * this file only moves JSON - it never calculates weights, reps or anything else.
 */

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://127.0.0.1:8000";
const PASSWORD_KEY = "gym-overload-password";
export const AUTH_EVENT = "gym-overload-auth-required";

// ---------- shapes returned by tools.py ----------

export type SetRow = { weight_kg: number; reps: number; rpe: number | null };
export type Settings = { rep_min: number; rep_max: number; increment_kg: number; target_sets: number };
export type SessionSummary = {
  date: string;
  deload: boolean;
  sets: SetRow[];
  working_weight_kg: number;
  total_reps: number;
};
export type Exercise = { exercise: string; equipment: string; settings: Settings };
export type Target = { weight_kg: number; target_reps: number[] };

export type RecommendationOk = {
  status: "ok";
  exercise: string;
  next: Target;
  rule: string;
  rule_explained: string;
  reason?: string;
  based_on: {
    last_session?: SessionSummary;
    recent_sessions?: SessionSummary[];
    settings: Settings;
    starting_weight_from?: "user";
  };
  e1rm_last_kg?: number;
};
export type NeedStartingWeight = {
  status: "need_starting_weight";
  exercise: string;
  settings: Settings;
  message: string;
};
export type Failure = { status: "error" | "parse_error" | "unknown_exercise"; message: string; exercises?: string[] };
export type Recommendation = RecommendationOk | NeedStartingWeight | Failure;

export type ProgressPoint = {
  date: string;
  deload: boolean;
  working_weight_kg: number;
  total_reps: number;
  volume_kg: number;
  best_e1rm_kg: number;
};
export type RecentSession = ProgressPoint & { exercise: string };
export type LoggedEntry = SessionSummary & { exercise: string; volume_kg: number };
export type PreviewEntry = { exercise: string; date: string; deload: boolean; sets: SetRow[] };

type Ok<T> = { status: "ok" } & T;
export type Result<T> = Ok<T> | Failure;

export type Meta = {
  log_help: string;
  defaults: { rep_min: number; rep_max: number; target_sets: number };
  default_increments_kg: Record<string, number>;
};
export type Reminders = {
  timezone: string;
  workout_days: string[];
  workout_time: string;
  missed_check_time: string;
  weekly_report_time: string;
  meal_times: string[];
  daily_cap: number;
  note: string;
};
export type Streak = {
  training_days: string[];
  current_streak: number;
  best_streak: number;
  consistency: { done: number; planned: number; percent: number | null; weeks: number };
  logged_today: boolean;
};
export type Meal = { id: number; date: string; text: string; protein_g: number | null; protein_estimated: boolean };
export type ProteinDay = {
  date: string;
  meals: Meal[];
  total_protein_g: number;
  meals_missing_protein: number;
  any_estimated: boolean;
  target_g: number | null;
  remaining_g: number | null;
};
export type MealResult = {
  meal: Meal;
  breakdown: { food: string; amount: string; protein_g: number }[];
  unknown_items: string[];
  message?: string;
  day: ProteinDay;
};
export type WeeklyLift = {
  exercise: string;
  sessions: number;
  best_e1rm_kg: number;
  previous_week_best_e1rm_kg: number | null;
  change_kg: number | null;
  plateau: boolean;
  deload: boolean;
};
export type WeeklyReport = {
  week: string;
  training_days_planned: number;
  training_days_done: number;
  sessions_logged: number;
  total_volume_kg: number;
  lifts: WeeklyLift[];
  protein: { on_target: number; days: number; target_g: number } | null;
  streak: number;
  text: string;
};
export type AppSettings = {
  training_days: string[];
  workout_time: string;
  day_plan: Record<string, string[]>;
  source: "app" | "defaults";
  goal: string | null;
  protein_target_g: number | null;
};

// ---------- transport ----------

export class ApiError extends Error {}

export function getStoredPassword(): string {
  try {
    return sessionStorage.getItem(PASSWORD_KEY) ?? "";
  } catch {
    return "";
  }
}

export function storePassword(password: string): void {
  try {
    if (password) sessionStorage.setItem(PASSWORD_KEY, password);
    else sessionStorage.removeItem(PASSWORD_KEY);
  } catch {
    /* private mode - the password just won't be remembered */
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", "X-App-Password": getStoredPassword(), ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(`Can't reach the API at ${API_URL}. Is it running?`);
  }
  if (res.status === 401) {
    window.dispatchEvent(new Event(AUTH_EVENT));
    throw new ApiError("Password required.");
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail = typeof body?.detail === "string" ? body.detail : `Request failed (${res.status}).`;
    throw new ApiError(detail);
  }
  return res.json() as Promise<T>;
}

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const enc = encodeURIComponent;

export const api = {
  auth: () => request<Ok<{ password_required: boolean }>>("/api/auth"),
  meta: () => request<Ok<Meta>>("/api/meta"),
  dashboard: () =>
    request<Ok<{ exercises: Exercise[]; next: Recommendation[]; recent: RecentSession[]; streak: Streak; protein: ProteinDay }>>(
      "/api/dashboard",
    ),
  report: () => request<Ok<WeeklyReport>>("/api/report"),
  meals: () => request<Ok<ProteinDay>>("/api/meals"),
  addMeal: (text: string) => request<Result<MealResult>>("/api/meals", post({ text })),
  fixMeal: (id: number, protein_g: number) =>
    request<Result<{ meal: Meal; day: ProteinDay }>>(`/api/meals/${id}/protein`, post({ protein_g })),
  settings: () => request<Ok<AppSettings>>("/api/settings"),
  saveSettings: (body: { training_days?: string; workout_time?: string; protein_target_g?: number; goal?: string }) =>
    request<Result<AppSettings>>("/api/settings", post(body)),
  /** Download a CSV through fetch so the optional password header is sent too. */
  download: async (kind: "workouts" | "meals") => {
    let res: Response;
    try {
      res = await fetch(`${API_URL}/api/export/${kind}.csv`, { headers: { "X-App-Password": getStoredPassword() } });
    } catch {
      throw new ApiError(`Can't reach the API at ${API_URL}. Is it running?`);
    }
    if (!res.ok) throw new ApiError(`Export failed (${res.status}).`);
    const url = URL.createObjectURL(await res.blob());
    const a = Object.assign(document.createElement("a"), { href: url, download: `gym-overload-${kind}.csv` });
    a.click();
    URL.revokeObjectURL(url);
  },
  exercises: () => request<Ok<{ exercises: Exercise[] }>>("/api/exercises"),
  addExercise: (body: {
    name: string;
    equipment: string;
    rep_min?: number;
    rep_max?: number;
    increment_kg?: number | null;
    target_sets?: number;
  }) => request<Result<{ exercise: string; equipment: string; settings: Settings }>>("/api/exercises", post(body)),
  nextAll: () => request<Ok<{ recommendations: Recommendation[] }>>("/api/next"),
  firstSession: (exercise: string, starting_weight_kg: number) =>
    request<Recommendation>(`/api/exercises/${enc(exercise)}/first-session`, post({ starting_weight_kg })),
  progress: (exercise: string, lastN?: number) =>
    request<Result<{ exercise: string; sessions: ProgressPoint[] }>>(
      `/api/exercises/${enc(exercise)}/progress${lastN ? `?last_n=${lastN}` : ""}`,
    ),
  exerciseNext: (exercise: string) => request<Recommendation>(`/api/exercises/${enc(exercise)}/next`),
  preview: (text: string, date: string) =>
    request<Result<{ entries: PreviewEntry[]; unknown_exercises: string[] }>>("/api/workouts/preview", post({ text, date })),
  save: (text: string, date: string) =>
    request<Result<{ logged: LoggedEntry[]; recommendations: Recommendation[] }>>("/api/workouts", post({ text, date })),
  coach: (message: string, conversation_id: string) =>
    request<Result<{ reply: string; evidence: string | null }>>("/api/coach", post({ message, conversation_id })),
  reminders: () => request<Result<Reminders>>("/api/reminders"),
};
