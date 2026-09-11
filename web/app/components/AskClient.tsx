"use client";

import { FormEvent, useMemo, useState } from "react";
import { AgentAnswer, ToolEvent, ToolResult } from "../types";
import { EvidenceDrawer } from "./EvidenceDrawer";
import { ResultChart } from "./ResultChart";

const suggestions = [
  "What is the B10 life of PN-4471 at use conditions?",
  "Which lot of PN-4471 is anomalous?",
  "Is STATION-007 contact resistance drifting?",
  "What is the failure probability for PN-4471 by 500 hours?",
];

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export function AskClient() {
  const [question, setQuestion] = useState(suggestions[0]);
  const [events, setEvents] = useState<ToolEvent[]>([]);
  const [answer, setAnswer] = useState<AgentAnswer | null>(null);
  const [running, setRunning] = useState(false);
  const [selected, setSelected] = useState<ToolResult | null>(null);
  const resultsById = useMemo(() => new Map((answer?.tool_results ?? []).map((r) => [r.provenance?.result_id, r])), [answer]);

  async function submit(event?: FormEvent) {
    event?.preventDefault();
    if (!question.trim() || running) return;
    setRunning(true); setEvents([]); setAnswer(null); setSelected(null);
    try {
      const response = await fetch(`${API}/api/query/stream`, { method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({question}) });
      if (!response.ok || !response.body) throw new Error(`Request failed (${response.status})`);
      const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const {value, done} = await reader.read(); if (done) break;
        buffer += decoder.decode(value, {stream: true});
        const blocks = buffer.split("\n\n"); buffer = blocks.pop() ?? "";
        for (const block of blocks) {
          const name = block.match(/^event: (.+)$/m)?.[1]; const data = block.match(/^data: (.+)$/m)?.[1];
          if (!name || !data) continue;
          const payload = JSON.parse(data);
          setEvents((current) => [...current, {name, payload}]);
          if (name === "done") setAnswer(payload as AgentAnswer);
          if (name === "failed") throw new Error(String(payload.error));
        }
      }
    } catch (error) {
      setAnswer({status: "failed", answer: error instanceof Error ? error.message : "Request failed", claims: [], tool_results: []});
    } finally { setRunning(false); }
  }

  return (
    <main className="shell">
      <section className="hero"><p className="eyebrow">EVIDENCE-FIRST ANALYSIS</p><h1>Ask the test data.<br/><em>Verify every answer.</em></h1><p>Reliability estimates, censored lifetime models, anomaly attribution, and station trends—with every number linked to its method and query.</p></section>
      <section className="workspace">
        <form className="askBox" onSubmit={submit}>
          <textarea value={question} onChange={(e) => setQuestion(e.target.value)} aria-label="Reliability question" />
          <div className="askFooter"><span>⌘ Enter to run</span><button disabled={running}>{running ? "Analyzing…" : "Analyze"}<b>→</b></button></div>
        </form>
        <div className="suggestions">{suggestions.map((value) => <button key={value} onClick={() => setQuestion(value)}>{value}</button>)}</div>
        {(events.length > 0 || answer) && <div className="analysisGrid">
          <section className="timeline panel"><div className="panelTitle"><span>Execution</span><small>{running ? "LIVE" : "COMPLETE"}</small></div>{events.filter((event) => event.name !== "done").map((event, index) => <div className="timelineRow" key={`${event.name}-${index}`}><i className={event.name.includes("completed") || event.name.includes("validated") ? "done" : ""}/><div><strong>{event.name.replaceAll("_", " ")}</strong><small>{event.name === "tool_started" ? String(event.payload.tool) : "validated event"}</small></div></div>)}</section>
          <section className="answer panel"><div className="panelTitle"><span>Answer</span><small>{answer?.status?.toUpperCase() ?? "WORKING"}</small></div>{answer ? <><p className="answerText">{answer.answer}</p><ResultChart results={answer.tool_results}/><div className="evidenceLinks">{answer.claims.flatMap((claim) => claim.evidence).filter((value, index, all) => all.findIndex((other) => other.result_id === value.result_id) === index).map((evidence) => <button key={evidence.result_id} onClick={() => setSelected(resultsById.get(evidence.result_id) ?? null)}>↗ View evidence · {evidence.result_id.slice(-7)}</button>)}</div></> : <div className="skeleton"/>}</section>
        </div>}
      </section>
      <EvidenceDrawer result={selected} onClose={() => setSelected(null)} />
    </main>
  );
}
