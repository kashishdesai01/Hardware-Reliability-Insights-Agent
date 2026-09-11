"use client";

import { ToolResult } from "../types";

export function EvidenceDrawer({ result, onClose }: { result: ToolResult | null; onClose: () => void }) {
  if (!result) return null;
  return (
    <aside className="drawer" aria-label="Evidence drawer">
      <div className="drawerHeader">
        <div><small>EVIDENCE</small><h2>{result.provenance?.result_id ?? result.status}</h2></div>
        <button className="iconButton" onClick={onClose} aria-label="Close evidence">×</button>
      </div>
      <section className="drawerSection">
        <div className="metricGrid">
          <div><small>ROWS</small><strong>{result.provenance?.row_count ?? "—"}</strong></div>
          <div><small>EXCLUDED</small><strong>{result.provenance?.excluded_row_count ?? "—"}</strong></div>
          <div><small>ELAPSED</small><strong>{result.provenance ? `${result.provenance.elapsed_ms.toFixed(1)} ms` : "—"}</strong></div>
        </div>
      </section>
      <section className="drawerSection"><small>FILTERS</small><pre>{JSON.stringify(result.provenance?.filters_applied ?? {}, null, 2)}</pre></section>
      <section className="drawerSection"><small>PARAMETERIZED QUERY</small><pre>{result.provenance?.sql ?? "Not available"}</pre></section>
      {!!result.caveats?.length && <section className="drawerSection"><small>CAVEATS</small><ul>{result.caveats.map((value) => <li key={value}>{value}</li>)}</ul></section>}
      <section className="drawerSection"><small>STRUCTURED RESULT</small><pre>{JSON.stringify(result.data ?? result, null, 2)}</pre></section>
    </aside>
  );
}
