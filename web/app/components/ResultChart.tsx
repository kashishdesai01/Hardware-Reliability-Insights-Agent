"use client";

import { useEffect, useRef } from "react";
import { ToolResult } from "../types";

export function ResultChart({ results }: { results: ToolResult[] }) {
  const ref = useRef<HTMLDivElement>(null);
  const plotResult = results.find((result) => result.data?.vega_lite);
  const sourceId = String(plotResult?.data?.source_result_id ?? "");
  const source = results.find((result) => result.provenance?.result_id === sourceId);

  useEffect(() => {
    if (!ref.current || !plotResult?.data?.vega_lite || !source?.data) return;
    const values = Array.isArray(plotResult.data.chart_values)
      ? plotResult.data.chart_values
      : Array.isArray(source.data.groups)
        ? source.data.groups
        : Array.isArray(source.data.ranked_levels)
          ? source.data.ranked_levels
          : [];
    const referencedSpec = plotResult.data.vega_lite as Record<string, unknown>;
    const resolvedSpec = { ...referencedSpec, data: { values } };
    void import("vega-embed").then(({ default: embed }) =>
      embed(ref.current!, resolvedSpec as never, {
        actions: false,
        renderer: "svg",
        theme: "latimes",
      }),
    );
  }, [plotResult, source, sourceId]);

  if (!plotResult || !source) return null;
  return <div className="chart" ref={ref} aria-label="Validated result chart" />;
}
