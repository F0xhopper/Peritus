"use client";

import { Bar, BarChart, CartesianGrid, XAxis } from "recharts";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
  type ChartConfig,
} from "@/components/ui/chart";

const chartConfig = {
  builds: {
    label: "Builds",
    color: "var(--chart-1)",
  },
} satisfies ChartConfig;

export function BuildsChart({
  data,
}: {
  data: { date: string; builds: number }[];
}) {
  return (
    <ChartContainer config={chartConfig} className="aspect-auto h-40 w-full">
      <BarChart data={data} margin={{ left: 0, right: 0, top: 4 }}>
        <CartesianGrid vertical={false} stroke="var(--border)" />
        <XAxis
          dataKey="date"
          tickLine={false}
          axisLine={false}
          tickMargin={8}
          fontSize={11}
        />
        <ChartTooltip
          cursor={{ fill: "var(--muted)" }}
          content={<ChartTooltipContent hideLabel={false} indicator="dot" />}
        />
        <Bar dataKey="builds" fill="var(--color-builds)" radius={2} maxBarSize={28} />
      </BarChart>
    </ChartContainer>
  );
}
