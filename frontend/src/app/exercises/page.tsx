import type { Metadata } from "next";
import { ExercisesView } from "@/views/exercises";

export const metadata: Metadata = { title: "Exercises" };

export default function Page() {
  return <ExercisesView />;
}
