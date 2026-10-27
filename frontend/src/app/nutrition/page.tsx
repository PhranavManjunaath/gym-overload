import type { Metadata } from "next";
import { NutritionView } from "@/views/nutrition";

export const metadata: Metadata = { title: "Nutrition" };

export default function Page() {
  return <NutritionView />;
}
