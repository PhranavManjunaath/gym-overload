"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, ChevronDown, RotateCcw, Send, ShieldCheck } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/cn";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/surface";

type Message =
  | { role: "user"; text: string }
  | { role: "assistant"; text: string; evidence: string | null }
  | { role: "error"; text: string };

const CONVERSATION_KEY = "gym-overload-conversation";
const EXAMPLES = ["bench 60x10,10,9 @8", "What's next for squat?", "Add squat, barbell"];

function newConversationId(): string {
  return crypto.randomUUID();
}

function storedConversationId(): string {
  try {
    const id = sessionStorage.getItem(CONVERSATION_KEY) ?? newConversationId();
    sessionStorage.setItem(CONVERSATION_KEY, id);
    return id;
  } catch {
    return newConversationId();
  }
}

/** The "Numbers used" block from the agent - plain Python output, shown verbatim. */
function Evidence({ text }: { text: string }) {
  return (
    <details open className="group mt-3 rounded-xl border border-accent/25 bg-accent/[0.04]">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-2 rounded-xl px-3.5 py-2.5 text-[13px] font-medium [&::-webkit-details-marker]:hidden">
        <span className="flex items-center gap-2 text-accent">
          <ShieldCheck className="size-4" aria-hidden /> Numbers used
        </span>
        <ChevronDown className="size-4 text-muted transition-transform duration-150 group-open:rotate-180" aria-hidden />
      </summary>
      <pre className="overflow-x-auto whitespace-pre-wrap border-t border-accent/15 px-3.5 py-3 font-mono text-[12.5px] leading-relaxed text-fg/85 num">
        {text}
      </pre>
    </details>
  );
}

export function CoachView() {
  const [conversationId, setConversationId] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    setConversationId(storedConversationId());
  }, []);
  useEffect(() => {
    // Block body on purpose: scrollIntoView() returns a Promise in newer browsers,
    // and an effect must not return anything except a cleanup function.
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function send() {
    const text = input.trim();
    if (!text || sending || !conversationId) return;
    setInput("");
    setMessages((m) => [...m, { role: "user", text }]);
    setSending(true);
    try {
      const r = await api.coach(text, conversationId);
      setMessages((m) => [
        ...m,
        r.status === "ok" ? { role: "assistant", text: r.reply, evidence: r.evidence } : { role: "error", text: r.message },
      ]);
    } catch (e) {
      setMessages((m) => [...m, { role: "error", text: e instanceof Error ? e.message : String(e) }]);
    } finally {
      setSending(false);
      inputRef.current?.focus();
    }
  }

  function reset() {
    const id = newConversationId();
    try {
      sessionStorage.setItem(CONVERSATION_KEY, id);
    } catch {}
    setConversationId(id);
    setMessages([]);
  }

  return (
    <div className="flex min-h-[calc(100dvh-14rem)] flex-col lg:min-h-[calc(100dvh-8rem)]">
      <PageHeader
        title="AI coach"
        description="Log or ask in your own words. Every number is checked against your data, and the numbers used are shown under each answer."
        actions={
          messages.length > 0 && (
            <Button variant="ghost" size="sm" icon={<RotateCcw aria-hidden />} onClick={reset}>
              New conversation
            </Button>
          )
        }
      />

      <div className="flex-1" aria-live="polite">
        {messages.length === 0 && !sending && (
          <div className="flex flex-col items-center py-10 text-center">
            <div className="mb-4 grid size-11 place-items-center rounded-xl border border-border bg-elevated text-accent">
              <Bot className="size-5" aria-hidden />
            </div>
            <p className="font-medium">Same coach as Telegram, separate conversation.</p>
            <p className="mt-1 max-w-md text-sm text-muted">Try one of these:</p>
            <div className="mt-4 flex flex-wrap justify-center gap-2">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  onClick={() => {
                    setInput(ex);
                    inputRef.current?.focus();
                  }}
                  className="h-9 rounded-full border border-border bg-surface px-4 font-mono text-[13px] text-muted transition-colors hover:border-border-strong hover:text-fg"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        <ol className="flex flex-col gap-5">
          {messages.map((m, i) => (
            <li key={i} className={cn("flex", m.role === "user" ? "justify-end" : "justify-start")}>
              {m.role === "user" ? (
                <div className="max-w-[85%] rounded-2xl rounded-br-md bg-elevated px-4 py-2.5 text-[15px] whitespace-pre-wrap">{m.text}</div>
              ) : (
                <div className="flex max-w-[92%] gap-3 sm:max-w-[85%]">
                  <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-lg border border-border bg-surface text-accent">
                    <Bot className="size-4" aria-hidden />
                  </span>
                  <div className="min-w-0">
                    <p className={cn("text-[15px] leading-relaxed whitespace-pre-wrap", m.role === "error" && "text-danger")}>{m.text}</p>
                    {m.role === "assistant" && m.evidence && <Evidence text={m.evidence} />}
                  </div>
                </div>
              )}
            </li>
          ))}
          {sending && (
            <li className="flex gap-3" aria-label="Coach is thinking">
              <span className="grid size-7 place-items-center rounded-lg border border-border bg-surface text-accent">
                <Bot className="size-4" aria-hidden />
              </span>
              <span className="flex items-center gap-1 pt-1">
                {[0, 1, 2].map((d) => (
                  <span key={d} className="size-1.5 animate-bounce rounded-full bg-muted" style={{ animationDelay: `${d * 120}ms` }} />
                ))}
              </span>
            </li>
          )}
        </ol>
        <div ref={endRef} />
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
        className="sticky bottom-20 mt-6 lg:bottom-6"
      >
        <div className="flex items-end gap-2 rounded-2xl border border-border bg-surface p-2 shadow-lg shadow-black/30 focus-within:border-accent/50">
          <label htmlFor="coach-input" className="sr-only">Message the coach</label>
          <textarea
            id="coach-input"
            ref={inputRef}
            rows={1}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                send();
              }
            }}
            placeholder="e.g. bench 60x10,10,9 · what's next for squat?"
            className="max-h-40 min-h-11 flex-1 resize-none bg-transparent px-3 py-2.5 text-base text-fg placeholder:text-subtle focus:outline-none sm:text-[15px]"
          />
          <Button type="submit" variant="primary" className="size-11 px-0" aria-label="Send" disabled={!input.trim() || sending} loading={sending}>
            {!sending && <Send aria-hidden />}
          </Button>
        </div>
        <p className="mt-2 hidden px-2 text-xs text-subtle sm:block">Enter to send · Shift + Enter for a new line</p>
      </form>
    </div>
  );
}
