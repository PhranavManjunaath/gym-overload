"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ChevronDown, Eye, PenLine, Save } from "lucide-react";
import { api, type LoggedEntry, type PreviewEntry, type Recommendation, type RecommendationOk } from "@/lib/api";
import { day, rpeLine, setsLine, titleCase, todayIso } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { Button } from "@/components/ui/button";
import { Field, Input, Textarea } from "@/components/ui/form";
import { Alert, Badge, Card, PageHeader, Skeleton } from "@/components/ui/surface";
import { RecommendationCard } from "@/components/workout/recommendation-card";
import { SetsTable } from "@/components/workout/sets-table";

type Preview =
  | { kind: "empty" }
  | { kind: "loading" }
  | { kind: "ok"; entries: PreviewEntry[]; unknown: string[] }
  | { kind: "error"; message: string };

type Saved = { logged: LoggedEntry[]; recommendations: Recommendation[] };

const PREVIEW_DELAY_MS = 350;

export function LogView() {
  const meta = useApi(() => api.meta());
  const [date, setDate] = useState(todayIso);
  const [text, setText] = useState("");
  const [result, setResult] = useState<{ key: string; preview: Preview } | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState<Saved | null>(null);

  // Live preview: the Python parser is the authority - nothing is corrected here.
  // The shown preview always belongs to the current text+date; anything older reads as "loading".
  const key = `${date}\n${text}`;
  const preview: Preview = !text.trim()
    ? { kind: "empty" }
    : result?.key === key
      ? result.preview
      : { kind: "loading" };

  useEffect(() => {
    if (!text.trim()) return;
    let active = true;
    const t = setTimeout(async () => {
      let p: Preview;
      try {
        const r = await api.preview(text, date);
        p = r.status === "ok" ? { kind: "ok", entries: r.entries, unknown: r.unknown_exercises } : { kind: "error", message: r.message };
      } catch (e) {
        p = { kind: "error", message: e instanceof Error ? e.message : String(e) };
      }
      if (active) setResult({ key: `${date}\n${text}`, preview: p });
    }, PREVIEW_DELAY_MS);
    return () => {
      active = false;
      clearTimeout(t);
    };
  }, [text, date]);

  const canSave = preview.kind === "ok" && preview.unknown.length === 0 && !saving;

  async function save() {
    if (!canSave) return;
    setSaving(true);
    setSaveError(null);
    try {
      const r = await api.save(text, date);
      if (r.status === "ok") {
        setSaved({ logged: r.logged, recommendations: r.recommendations });
        setText("");
      } else {
        setSaveError(r.message);
      }
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  if (saved) {
    return (
      <>
        <PageHeader title="Log workout" />
        <Alert tone="success" title="Workout saved">
          The numbers below are exactly what was stored.
        </Alert>
        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          {saved.logged.map((e) => (
            <Card key={e.exercise + e.date} className="p-5">
              <div className="flex items-center justify-between gap-3">
                <h3 className="font-semibold">{titleCase(e.exercise)}</h3>
                <span className="flex items-center gap-2 text-sm text-muted num">
                  {day(e.date)} {e.deload && <Badge tone="warning">Deload</Badge>}
                </span>
              </div>
              <div className="mt-3">
                <SetsTable sets={e.sets} />
              </div>
            </Card>
          ))}
        </div>
        <h2 className="mb-3 mt-10 text-[13px] font-medium uppercase tracking-[0.08em] text-muted">Next session</h2>
        <div className="grid gap-4 lg:grid-cols-2">
          {saved.recommendations.map((r) =>
            r.status === "ok" ? <RecommendationCard key={r.exercise} rec={r as RecommendationOk} showLogAction={false} /> : null,
          )}
        </div>
        <div className="mt-8">
          <Button variant="primary" icon={<PenLine aria-hidden />} onClick={() => setSaved(null)}>
            Log another workout
          </Button>
        </div>
      </>
    );
  }

  return (
    <>
      <PageHeader title="Log workout" description="Same format as Telegram. Nothing is saved until you press Save." />

      <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* Input */}
        <Card className="p-5 sm:p-6">
          <div className="flex flex-col gap-5">
            <Field label="Date" htmlFor="log-date" className="sm:max-w-[220px]">
              <Input id="log-date" type="date" value={date} max={todayIso()} onChange={(e) => setDate(e.target.value || todayIso())} />
            </Field>
            <Field label="Workout" htmlFor="log-text" hint="One exercise per line. Weights in kg, decimals with a dot (62.5).">
              <Textarea
                id="log-text"
                rows={6}
                value={text}
                onChange={(e) => {
                  setText(e.target.value);
                  setSaveError(null);
                }}
                placeholder={"bench 60x10,10,9 @8\nsquat 100x5,5,5"}
                spellCheck={false}
                autoCapitalize="none"
                autoCorrect="off"
              />
            </Field>

            <details className="group rounded-xl border border-border">
              <summary className="flex cursor-pointer list-none items-center justify-between rounded-xl px-4 py-3 text-sm font-medium hover:bg-elevated/50 [&::-webkit-details-marker]:hidden">
                Format help
                <ChevronDown className="size-4 text-muted transition-transform duration-150 group-open:rotate-180" aria-hidden />
              </summary>
              <div className="border-t border-border px-4 py-3">
                {meta.data ? (
                  <pre className="whitespace-pre-wrap font-mono text-[13px] leading-relaxed text-muted">{meta.data.log_help}</pre>
                ) : (
                  <Skeleton className="h-24 w-full" />
                )}
              </div>
            </details>
          </div>
        </Card>

        {/* Preview */}
        <Card className="p-5 sm:p-6 lg:sticky lg:top-10">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h2 className="flex items-center gap-2 font-semibold">
              <Eye className="size-[18px] text-muted" aria-hidden /> Preview
            </h2>
            <Badge>Not saved yet</Badge>
          </div>

          <div aria-live="polite">
            {preview.kind === "empty" && (
              <p className="py-8 text-center text-sm text-muted">Type a workout to see exactly what will be saved.</p>
            )}
            {preview.kind === "loading" && (
              <div className="flex flex-col gap-3 py-2" aria-busy="true">
                <Skeleton className="h-5 w-40" />
                <Skeleton className="h-24 w-full" />
              </div>
            )}
            {preview.kind === "error" && (
              <Alert tone="error" title="Couldn't read this workout">
                <pre className="whitespace-pre-wrap font-sans">{preview.message}</pre>
              </Alert>
            )}
            {preview.kind === "ok" && (
              <div className="flex flex-col gap-5">
                {preview.entries.map((e, i) => {
                  const rpe = rpeLine(e.sets);
                  return (
                    <div key={i}>
                      <div className="flex flex-wrap items-center justify-between gap-2">
                        <h3 className="font-medium">{titleCase(e.exercise)}</h3>
                        <span className="flex items-center gap-2 text-sm text-muted num">
                          {day(e.date)} {e.deload && <Badge tone="warning">Deload</Badge>}
                        </span>
                      </div>
                      <p className="mt-0.5 text-[13px] text-muted num">
                        {setsLine(e.sets)}
                        {rpe && ` · ${rpe}`}
                      </p>
                      <div className="mt-2">
                        <SetsTable sets={e.sets} />
                      </div>
                    </div>
                  );
                })}
                {preview.unknown.length > 0 && (
                  <Alert tone="warning" title={`Not set up yet: ${preview.unknown.join(", ")}`}>
                    Add {preview.unknown.length === 1 ? "it" : "them"} on the{" "}
                    <Link href="/exercises" className="font-medium text-fg underline underline-offset-4 hover:text-accent">
                      Exercises page
                    </Link>{" "}
                    first.
                  </Alert>
                )}
              </div>
            )}
          </div>

          {saveError && (
            <Alert tone="error" title="Nothing was saved" className="mt-4">
              {saveError}
            </Alert>
          )}

          <div className="mt-6 border-t border-border pt-5">
            <Button variant="primary" size="lg" className="w-full" icon={<Save aria-hidden />} loading={saving} disabled={!canSave} onClick={save}>
              {saving ? "Saving…" : "Save workout"}
            </Button>
          </div>
        </Card>
      </div>
    </>
  );
}
