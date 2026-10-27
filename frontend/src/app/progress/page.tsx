import type { Metadata } from "next";
import { ProgressView } from "@/views/progress";

export const metadata: Metadata = { title: "Progress" };

export default function Page() {
  return <ProgressView />;
}
