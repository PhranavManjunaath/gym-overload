"use client";

import type { ReactNode } from "react";
import { Bell, CalendarDays, Clock, Globe, Lock, Server, Utensils } from "lucide-react";
import { API_URL, api } from "@/lib/api";
import { titleCase } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Alert, Badge, Card, LoadError, PageHeader, Section, Skeleton } from "@/components/ui/surface";

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
      <div className="flex flex-wrap gap-1.5 pl-8 text-[15px] num sm:pl-0 sm:justify-end">{children}</div>
    </div>
  );
}

export function SettingsView() {
  const reminders = useApi(() => api.reminders());
  const auth = useApi(() => api.auth());
  const r = reminders.data;

  return (
    <>
      <PageHeader title="Settings" description="Read-only for now - these show how the app and the Telegram bot are configured." />

      <Section title="Reminders">
        {reminders.error && <LoadError message={reminders.error} onRetry={reminders.reload} />}
        {reminders.loading && !r && <Skeleton className="h-64 rounded-card" />}
        {r && r.status !== "ok" && <Alert tone="error" title="Reminder settings are invalid">{r.message}</Alert>}
        {r && r.status === "ok" && (
          <>
            <Card className="divide-y divide-border">
              <Row icon={<Globe />} label="Timezone">{r.timezone}</Row>
              <Row icon={<CalendarDays />} label="Workout days">
                {r.workout_days.map((d) => <Badge key={d}>{titleCase(d)}</Badge>)}
              </Row>
              <Row icon={<Bell />} label="Workout reminder" description="Today's targets, straight from the engine">
                {r.workout_time}
              </Row>
              <Row icon={<Clock />} label="Missed-workout check" description="Only if nothing was logged that day">
                {r.missed_check_time}
              </Row>
              <Row icon={<Utensils />} label="Meal reminders">
                {r.meal_times.length ? r.meal_times.map((t) => <Badge key={t}>{t}</Badge>) : <span className="text-muted">Off</span>}
              </Row>
            </Card>
            <Alert tone="info" className="mt-3">
              Reminders are sent by the Telegram bot. {r.note}
            </Alert>
          </>
        )}
      </Section>

      <Section title="App">
        <Card className="divide-y divide-border">
          <Row icon={<Lock />} label="Password protection" description="Set WEB_PASSWORD in .env to require a password">
            {auth.data ? (
              auth.data.password_required ? <Badge tone="success">On</Badge> : <Badge>Off</Badge>
            ) : (
              <Skeleton className="h-6 w-12" />
            )}
          </Row>
          <Row icon={<Server />} label="API" description="Every number comes from this Python server">
            <code className="font-mono text-[13px] text-muted">{API_URL}</code>
          </Row>
        </Card>
      </Section>
    </>
  );
}
