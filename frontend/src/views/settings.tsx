"use client";

import { useState, type ReactNode } from "react";
import { Bell, Clock, Download, FileSpreadsheet, Globe, Lock, Server, Target, Utensils } from "lucide-react";
import { API_URL, api, type AppSettings } from "@/lib/api";
import { cn } from "@/lib/cn";
import { titleCase } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Badge, Card, LoadError, PageHeader, Section, Skeleton } from "@/components/ui/surface";

const WEEK = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];

function Row({ icon, label, description, children }: { icon: ReactNode; label: string; description?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 px-5 py-4 sm:flex-row sm:items-center sm:justify-between sm:gap-6">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 text-muted [&_svg]:size-[18px]">{icon}</span>
        <div>
          <p className="text-[15px] font-medium">{label}</p>
          {description && <p className="mt-0.5 text-[13px] text-muted">{description}</p>}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 pl-8 text-[15px] num sm:justify-end sm:pl-0">{children}</div>
    </div>
  );
}

function TrainingForm({ initial, onSaved }: { initial: AppSettings; onSaved: () => void }) {
  const [days, setDays] = useState<string[]>(initial.training_days);
  const [time, setTime] = useState(initial.workout_time);
  const [goal, setGoal] = useState(initial.goal ?? "");
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<{ tone: "success" | "error"; text: string } | null>(null);
  const toggle = (d: string) => setDays((cur) => (cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d]));

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setMsg(null);
    try {
      const r = await api.saveSettings({ training_days: days.join(","), workout_time: time, goal: goal.trim() || undefined });
      if (r.status === "ok") {
        setMsg({ tone: "success", text: "Saved. The bot uses the new schedule from its next check (within a minute)." });
        onSaved();
      } else setMsg({ tone: "error", text: r.message });
    } catch (err) {
      setMsg({ tone: "error", text: err instanceof Error ? err.message : String(err) });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="p-5 sm:p-6">
      <form onSubmit={save} className="flex flex-col gap-5">
        <fieldset>
          <legend className="text-[13px] font-medium">Training days</legend>
          <div className="mt-2 flex flex-wrap gap-2" role="group" aria-label="Training days">
            {WEEK.map((d) => {
              const on = days.includes(d);
              return (
                <button
                  key={d}
                  type="button"
                  role="switch"
                  aria-checked={on}
                  onClick={() => toggle(d)}
                  className={cn(
                    "h-10 min-w-12 rounded-lg border px-3 text-sm font-medium transition-colors duration-150 cursor-pointer",
                    on ? "border-accent/50 bg-accent/10 text-accent" : "border-border bg-bg text-muted hover:text-fg",
                  )}
                >
                  {titleCase(d)}
                </button>
              );
            })}
          </div>
          <p className="mt-2 text-[13px] text-muted">Streaks and consistency count these days only.</p>
        </fieldset>
        <Field label="Workout reminder time" htmlFor="workout-time" className="sm:max-w-[200px]">
          <Input id="workout-time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        </Field>
        <Field label="Goal" htmlFor="goal" hint="In your own words - the AI coach sees it every time.">
          <Input id="goal" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="e.g. bench 100 kg by June" maxLength={300} />
        </Field>
        {msg && <Alert tone={msg.tone}>{msg.text}</Alert>}
        <Button type="submit" variant="primary" loading={saving} disabled={days.length === 0 || !time} className="sm:self-start">
          Save training settings
        </Button>
      </form>
    </Card>
  );
}

export function SettingsView() {
  const settings = useApi(() => api.settings());
  const reminders = useApi(() => api.reminders());
  const auth = useApi(() => api.auth());
  const [exportError, setExportError] = useState<string | null>(null);
  const r = reminders.data;

  async function download(kind: "workouts" | "meals") {
    setExportError(null);
    try {
      await api.download(kind);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <>
      <PageHeader title="Settings" description="Your training schedule, reminders and data." />

      <Section title="Training">
        {settings.error && <LoadError message={settings.error} onRetry={settings.reload} />}
        {settings.loading && !settings.data && <Skeleton className="h-72 rounded-card" />}
        {settings.data && (
          <TrainingForm
            key={`${settings.data.training_days.join()}-${settings.data.workout_time}-${settings.data.goal}`}
            initial={settings.data}
            onSaved={() => {
              settings.reload();
              reminders.reload();
            }}
          />
        )}
      </Section>

      <Section title="Reminders (Telegram)">
        {reminders.error && <LoadError message={reminders.error} onRetry={reminders.reload} />}
        {reminders.loading && !r && <Skeleton className="h-48 rounded-card" />}
        {r && r.status !== "ok" && <Alert tone="error" title="Reminder settings are invalid">{r.message}</Alert>}
        {r && r.status === "ok" && (
          <>
            <Card className="divide-y divide-border">
              <Row icon={<Globe />} label="Timezone">{r.timezone}</Row>
              <Row icon={<Bell />} label="Messages per day" description="Workout messages always get priority">
                At most {r.daily_cap}
              </Row>
              <Row icon={<Clock />} label="Missed-workout nudge" description="Only on training days with nothing logged">
                {r.missed_check_time}
              </Row>
              <Row icon={<Target />} label="Weekly report">Sunday {r.weekly_report_time}</Row>
              <Row icon={<Utensils />} label="Meal reminders" description="Only when a slot is free">
                {r.meal_times.length ? r.meal_times.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-muted">Off</span>}
              </Row>
            </Card>
            <Alert tone="info" className="mt-3">{r.note}</Alert>
          </>
        )}
      </Section>

      <Section title="Your data">
        <Card className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6">
          <div className="flex items-start gap-3">
            <FileSpreadsheet className="mt-0.5 size-[18px] text-muted" aria-hidden />
            <div>
              <p className="text-[15px] font-medium">Export to CSV</p>
              <p className="mt-0.5 text-[13px] text-muted">Every set you&apos;ve logged, and every meal - opens in Excel or Google Sheets.</p>
            </div>
          </div>
          <div className="flex flex-wrap gap-2 pl-8 sm:pl-0">
            <Button size="sm" icon={<Download aria-hidden />} onClick={() => download("workouts")}>Workouts</Button>
            <Button size="sm" icon={<Download aria-hidden />} onClick={() => download("meals")}>Meals</Button>
          </div>
        </Card>
        {exportError && <Alert tone="error" className="mt-3">{exportError}</Alert>}
      </Section>

      <Section title="App">
        <Card className="divide-y divide-border">
          <Row icon={<Lock />} label="Password protection" description="Set WEB_PASSWORD in .env to require a password">
            {auth.data ? (auth.data.password_required ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>) : <Skeleton className="h-6 w-12" />}
          </Row>
          <Row icon={<Server />} label="API" description="Every number comes from this Python server">
            <code className="font-mono text-[13px] text-muted">{API_URL}</code>
          </Row>
        </Card>
      </Section>
    </>
  );
}
