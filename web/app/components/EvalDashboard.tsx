"use client";

import { useEffect, useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type FamilyMetrics = { passed: number; total: number; pass_rate: number; p95_latency_ms: number };
type EvalReport = { generated_at: string; split: string; passed: number; total: number; per_family: Record<string, FamilyMetrics> };

export function EvalDashboard() {
  const [report, setReport] = useState<EvalReport | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void fetch(`${API}/api/evals/latest`)
      .then((response) => {
        if (!response.ok) throw new Error(`Report request failed (${response.status})`);
        return response.json() as Promise<EvalReport>;
      })
      .then(setReport)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Report failed"));
  }, []);

  return <main className="shell subpage">
    <p className="eyebrow">EVALUATIONS</p><h1>Quality by family</h1>
    <p className="lede">A committed report, broken down so one strong family cannot hide a regression in another.</p>
    {error && <section className="notice panel">{error}</section>}
    {!report && !error && <section className="empty panel"><strong>Loading the latest committed report…</strong></section>}
    {report && <>
      <section className="evalSummary panel"><div><small>PASSING</small><strong>{report.passed} / {report.total}</strong></div><div><small>SPLIT</small><strong>{report.split}</strong></div><div><small>GENERATED</small><strong>{new Date(report.generated_at).toLocaleString()}</strong></div></section>
      <section className="evalTable panel"><div className="evalRow evalHead"><span>Family</span><span>Pass</span><span>Rate</span><span>p95 latency</span></div>{Object.entries(report.per_family).sort(([left], [right]) => left.localeCompare(right)).map(([family, metrics]) => <div className="evalRow" key={family}><strong>{family.replaceAll("_", " ")}</strong><span>{metrics.passed} / {metrics.total}</span><span>{(metrics.pass_rate * 100).toFixed(0)}%</span><span>{metrics.p95_latency_ms.toFixed(1)} ms</span></div>)}</section>
    </>}
  </main>;
}
