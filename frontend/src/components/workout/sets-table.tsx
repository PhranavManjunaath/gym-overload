import type { SetRow } from "@/lib/api";
import { num } from "@/lib/format";

/** Set-by-set table: weight, reps and RPE exactly as parsed/stored. */
export function SetsTable({ sets }: { sets: SetRow[] }) {
  const hasRpe = sets.some((s) => s.rpe !== null);
  return (
    <table className="w-full text-sm num">
      <thead>
        <tr className="border-b border-border text-left text-xs text-muted">
          <th scope="col" className="py-2 pr-3 font-medium">Set</th>
          <th scope="col" className="py-2 pr-3 text-right font-medium">Weight</th>
          <th scope="col" className="py-2 pr-3 text-right font-medium">Reps</th>
          {hasRpe && <th scope="col" className="py-2 text-right font-medium">RPE</th>}
        </tr>
      </thead>
      <tbody>
        {sets.map((s, i) => (
          <tr key={i} className="border-b border-border/60 last:border-0">
            <td className="py-2 pr-3 text-muted">{i + 1}</td>
            <td className="py-2 pr-3 text-right">{num(s.weight_kg)} <span className="text-muted">kg</span></td>
            <td className="py-2 pr-3 text-right">{s.reps}</td>
            {hasRpe && <td className="py-2 text-right">{s.rpe === null ? <span className="text-subtle">–</span> : num(s.rpe)}</td>}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
