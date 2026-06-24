// TS mirror of carrystar/contracts.py. Keep field names in lockstep.

export const TRACKER_COLUMNS = [
  "account",
  "bol_number",
  "container",
  "date_of_etd",
  "import_po",
  "style",
  "customer_po",
  "ctn_qty",
  "pallet",
  "pc_qty",
  "rush_carton",
  "ds",
  "wms_ticket",
  "needs_labels",
] as const;

export type TrackerColumn = (typeof TRACKER_COLUMNS)[number];

export const TRANSCRIPTION_COLUMNS: TrackerColumn[] = [
  "account", "bol_number", "container", "date_of_etd", "import_po",
  "style", "customer_po", "ctn_qty", "pallet", "pc_qty",
];

export const INTERNAL_COLUMNS: TrackerColumn[] = [
  "rush_carton", "ds", "wms_ticket", "needs_labels",
];

export type StatusColor = "green" | "blue" | "red" | "plain";

export interface SourceRef {
  doc_name: string;
  locator: string;
}

export interface TrackerRow {
  row_id: string;
  shipment_id: string;
  account: string;
  bol_number: string;
  container: string;
  date_of_etd: string;
  import_po: string;
  style: string;
  customer_po: string;
  ctn_qty: number;
  pallet: string;
  pc_qty: number;
  rush_carton: string;
  ds: string;
  wms_ticket: string;
  needs_labels: string;
  status_color: StatusColor;
  source_refs: SourceRef[];
}

export type MutationType = "add_row" | "update_field" | "remove_row";
export type MutationStatus = "pending" | "approved" | "rejected" | "edited" | "superseded";
export type Classification =
  | "matched" | "new_order" | "added_po" | "field_change" | "missing_row" | "internal_flag" | "rescinded";

export interface Mutation {
  mutation_id: string;
  type: MutationType;
  shipment_id: string;
  row_id: string | null;
  field: string | null;
  old_value: string | null;
  new_value: string;
  sources: SourceRef[];
  confidence: number;
  status: MutationStatus;
  agent_note: string;
  classification: Classification;
  proposed_row: TrackerRow | null;
}

export type EventType =
  | "hello" | "email_received" | "triage" | "extract" | "recon"
  | "proposal" | "mutation_status" | "retraction" | "committed" | "state" | "log" | "done" | "error";

export interface StreamEvent<T = any> {
  type: EventType;
  data: T;
}

export interface StateSnapshot {
  rows: TrackerRow[];
  pending: Mutation[];
  replay_running: boolean;
  beat_cursor: number;
  total_beats: number;
  has_next: boolean;
}
