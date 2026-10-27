"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { ProgressPoint } from "@/lib/api";
import { day, kg, shortDay } from "@/lib/format";

type Metric = "working_weight_kg" | "best_e1rm_kg" | "volume_kg";

const C = {
  grid: "#292f29",
  axis: "#7c847b",
  accent: "#c7f36b",
  warning: "#e8b04b",
  bar: "#9cc556",
};

type TooltipProps = {
  active?: boolean;
  payload?: ReadonlyArray<{ value?: unknown; payload?: unknown }>;
  label?: unknown;
};

function ChartTooltip({ active, payload, label }: TooltipProps) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload as ProgressPoint;
  return (
    <div className="rounded-lg border border-border bg-elevated px-3 py-2 text-[13px] shadow-lg num">
      <p className="text-muted">{day(String(label), true)}</p>
      <p className="mt-0.5 font-medium text-fg">{kg(Number(payload[0].value))}</p>
      {p.deload && <p className="mt-0.5 text-warning">Deload session</p>}
    </div>
  );
}

const axisProps = {
  stroke: C.axis,
  tickLine: false,
  axisLine: false,
  fontSize: 12,
  fontFamily: "var(--font-geist-mono)",
} as const;

/** One metric over time. Values are plotted as returned by the API - nothing is computed. */
export function ProgressChart({ data, metric, kind = "line" }: { data: ProgressPoint[]; metric: Metric; kind?: "line" | "bar" }) {
  const common = (
    <>
      <CartesianGrid stroke={C.grid} strokeDasharray="3 4" vertical={false} />
      <XAxis dataKey="date" tickFormatter={shortDay} minTickGap={24} dy={6} {...axisProps} />
      <YAxis width={48} domain={["auto", "auto"]} tickFormatter={(v: number) => `${v}`} {...axisProps} />
      <Tooltip content={(p) => <ChartTooltip active={p.active} payload={p.payload} label={p.label} />} cursor={{ stroke: C.grid, fill: "rgba(255,255,255,0.03)" }} />
    </>
  );
  return (
    <div className="h-56 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {kind === "bar" ? (
          <BarChart data={data} margin={{ top: 8, right: 8, left: -8, bottom: 0 }}>
            {common}
            <Bar dataKey={metric} radius={[4, 4, 0, 0]} maxBarSize={36} fill={C.bar} />
          </BarChart>
        ) : (
          <LineChart data={data} margin={{ top: 8, right: 12, left: -8, bottom: 0 }}>
            {common}
            <Line
              type="monotone"
              dataKey={metric}
              stroke={C.accent}
              strokeWidth={2}
              isAnimationActive={false}
              dot={(props: { cx?: number; cy?: number; payload?: ProgressPoint; index?: number }) => (
                <circle
                  key={props.index}
                  cx={props.cx}
                  cy={props.cy}
                  r={3.5}
                  fill={props.payload?.deload ? C.warning : C.accent}
                  stroke="#0b0d0c"
                  strokeWidth={1.5}
                />
              )}
              activeDot={{ r: 5, stroke: "#0b0d0c", strokeWidth: 2 }}
            />
          </LineChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
