"use client";

import { Lock } from "lucide-react";
import { useEffect, useState } from "react";
import { api, AUTH_EVENT, getStoredPassword, storePassword } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/form";
import { Alert, Card } from "@/components/ui/surface";

/**
 * Optional single-user password (WEB_PASSWORD on the API). The API checks it on
 * every request; this screen only collects it. Not multi-user authentication.
 */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const [locked, setLocked] = useState(false);
  const [typed, setTyped] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    api
      .auth()
      .then((r) => r.password_required && !getStoredPassword() && setLocked(true))
      .catch(() => {}); // unreachable API is reported by each page
    const lock = () => setLocked(true);
    window.addEventListener(AUTH_EVENT, lock);
    return () => window.removeEventListener(AUTH_EVENT, lock);
  }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setChecking(true);
    setError(null);
    storePassword(typed);
    try {
      await api.exercises();
      setLocked(false);
      setTyped("");
      window.location.reload();
    } catch {
      storePassword("");
      setError("Wrong password.");
    } finally {
      setChecking(false);
    }
  }

  if (!locked) return <>{children}</>;
  return (
    <div className="mx-auto mt-12 max-w-sm">
      <Card className="p-6">
        <div className="mb-5 grid size-11 place-items-center rounded-xl border border-border bg-elevated text-accent">
          <Lock className="size-5" aria-hidden />
        </div>
        <h1 className="text-xl font-semibold">Enter password</h1>
        <p className="mt-1 text-sm text-muted">This app is protected with WEB_PASSWORD.</p>
        <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
          <Field label="Password" htmlFor="password">
            <Input id="password" type="password" autoComplete="current-password" value={typed} onChange={(e) => setTyped(e.target.value)} autoFocus />
          </Field>
          {error && <Alert tone="error">{error}</Alert>}
          <Button type="submit" variant="primary" loading={checking} disabled={!typed}>
            Log in
          </Button>
        </form>
      </Card>
    </div>
  );
}
