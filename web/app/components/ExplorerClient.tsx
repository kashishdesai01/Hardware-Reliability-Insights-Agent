"use client";

import { useEffect, useState } from "react";
import { AgentAnswer } from "../types";
import { ResultChart } from "./ResultChart";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
type Catalog = { parts: string[]; lots: string[]; stations: string[] };
type Dimension = keyof Catalog;

export function ExplorerClient() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [dimension, setDimension] = useState<Dimension>("parts");
  const [selection, setSelection] = useState("");
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    void fetch(`${API}/api/explorer/catalog`)
      .then((response) => {
        if (!response.ok) throw new Error(`Catalog request failed (${response.status})`);
        return response.json() as Promise<Catalog>;
      })
      .then((value) => {
        setCatalog(value);
        setSelection(value.parts[0] ?? "");
      })
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Catalog failed"))
      .finally(() => setLoading(false));
  }, []);

  function switchDimension(value: Dimension) {
    setDimension(value);
    setSelection(catalog?.[value][0] ?? "");
    setAnswer(null);
  }

  async function analyze() {
    if (!selection) return;
    setLoading(true);
    setError("");
    const question = dimension === "parts"
      ? `What is the B10 lifetime of ${selection} at use conditions?`
      : dimension === "lots"
        ? `What is the B10 lifetime of lot ${selection} at use conditions?`
        : `Is ${selection} contact resistance drifting?`;
    try {
      const response = await fetch(`${API}/api/query`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      if (!response.ok) throw new Error(`Analysis request failed (${response.status})`);
      setAnswer((await response.json()) as AgentAnswer);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  return <main className="shell subpage">
    <p className="eyebrow">EXPLORER</p><h1>Qualification cohorts</h1>
    <p className="lede">Browse canonical parts, lots, and stations. Curves and trends come from the same typed tools used by Ask.</p>
    <section className="explorerControls panel">
      <div className="tabs" role="tablist">{(["parts", "lots", "stations"] as Dimension[]).map((value) => <button key={value} className={dimension === value ? "active" : ""} onClick={() => switchDimension(value)}>{value}</button>)}</div>
      {catalog && <select aria-label="Cohort selection" value={selection} onChange={(event) => setSelection(event.target.value)}>{catalog[dimension].map((value) => <option key={value}>{value}</option>)}</select>}
      <button className="primary" disabled={loading || !selection} onClick={analyze}>{loading ? "Loading…" : dimension === "stations" ? "Analyze trend" : "Fit survival"}</button>
    </section>
    {error && <section className="notice panel">{error}</section>}
    {answer && <section className="explorerResult panel"><div className="panelTitle"><span>Typed analysis</span><small>{answer.status}</small></div><p className="answerText">{answer.answer}</p><ResultChart results={answer.tool_results}/></section>}
  </main>;
}
