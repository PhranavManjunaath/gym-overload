import type { Metadata } from "next";
import { Suspense } from "react";
import { Skeleton } from "@/components/ui/surface";
import { LogView } from "@/views/log";

export const metadata: Metadata = { title: "Log workout" };

export default function Page() {
  // LogView reads today's date, which must be computed when the page is opened, not at build time.
  return (
    <Suspense fallback={<Skeleton className="h-96 rounded-card" />}>
      <LogView />
    </Suspense>
  );
}
