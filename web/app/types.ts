export type ToolEvent = {
  name: string;
  payload: Record<string, unknown>;
};

export type Provenance = {
  tool_call_id: string;
  result_id: string;
  dataset_version: string;
  sql: string;
  row_count: number;
  excluded_row_count: number;
  filters_applied: Record<string, unknown>;
  elapsed_ms: number;
};

export type ToolResult = {
  status: string;
  data?: Record<string, unknown>;
  reason?: string;
  caveats?: string[];
  provenance?: Provenance;
};

export type AgentAnswer = {
  status: string;
  answer: string;
  claims: Array<{
    text: string;
    evidence: Array<{
      result_id: string;
      json_path: string;
      value: number;
      display: string;
      unit?: string;
    }>;
  }>;
  tool_results: ToolResult[];
};
