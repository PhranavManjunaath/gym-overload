"use client";

import { Dumbbell } from "lucide-react";
import { api, type NeedStartingWeight, type RecommendationOk } from "@/lib/api";
import { useApi } from "@/lib/use-api";
import { ButtonLink } from "@/components/ui/button";
import { Alert, Card, EmptyState, LoadError, PageHeader, Skeleton } from "@/components/ui/surface";
import { RecommendationCard } from "@/components/workout/recommendation-card";
import { StartingWeightCard } from "@/components/workout/starting-weight-card";

export function NextView() {
  const { data, error, loading, reload } = useApi(() => api.nextAll());

  return (
    <>
      <PageHeader
        title="Next session"
        description="Picked by the progression engine from your logged sets. Open Evidence on any card to check the numbers."
      />

      {loading && !data && (
        <div className="grid gap-4 lg:grid-cols-2" aria-busy="true" aria-label="Loading">
          {[0, 1].map((i) => (
            <Card key={i} className="p-6">
              <Skeleton className="h-6 w-32" />
              <Skeleton className="mt-6 h-11 w-36" />
              <Skeleton className="mt-3 h-4 w-44" />
              <Skeleton className="mt-6 h-12 w-full" />
            </Card>
          ))}
        </div>
      )}
      {error && <LoadError message={error} onRetry={reload} />}

      {data && data.recommendations.length === 0 && (
        <EmptyState
          icon={<Dumbbell />}
          title="No exercises yet"
          description="Add an exercise first. Recommendations come from your own logged sets."
          actions={<ButtonLink href="/exercises" variant="primary">Add exercise</ButtonLink>}
        />
      )}

      {data && data.recommendations.length > 0 && (
        <div className="grid items-start gap-4 lg:grid-cols-2">
          {data.recommendations.map((r, i) =>
            r.status === "ok" ? (
              <RecommendationCard key={r.exercise} rec={r as RecommendationOk} />
            ) : r.status === "need_starting_weight" ? (
              <StartingWeightCard key={r.exercise} rec={r as NeedStartingWeight} />
            ) : (
              <Alert key={i} tone="warning">{r.message}</Alert>
            ),
          )}
        </div>
      )}
    </>
  );
}
