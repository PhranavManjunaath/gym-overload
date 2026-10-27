import type { Metadata } from "next";
import { NextView } from "@/views/next";

export const metadata: Metadata = { title: "Next session" };

export default function Page() {
  return <NextView />;
}
