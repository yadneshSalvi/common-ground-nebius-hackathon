export type OwnerId = "asha" | "ravi" | "leena";
export type Json =
  null | boolean | number | string | Json[] | { [key: string]: Json };
export interface Owner {
  id: OwnerId;
  name: string;
  role: string;
  accent: string;
  initials: string;
  url: string;
  key_id?: string;
  public_key?: string;
}
export interface Task {
  task_id: string;
  label: string;
  capability: string;
  duration: number;
  earliest: number;
  latest: number;
  location: string;
  predecessors: string[];
}
export interface Offer {
  offer_id: string;
  owner_id: OwnerId;
  revision: number;
  constraint_revision: number;
  capabilities: string[];
  task_ids: string[];
  start: number;
  end: number;
  capacity: number;
  preference_cost: number;
}
export interface Recipients {
  humans: string[];
  broker: string;
  inference: string[];
}
export interface ReleasePayload {
  goal_id: string;
  goal_revision: number;
  purpose: string;
  retention: string;
  recipients: Recipients;
  fields: string[];
  offer: Offer;
}
export interface Envelope<T> {
  body: {
    type: string;
    schema_version: number;
    message_id: string;
    issuer: OwnerId;
    audience: string[];
    circle_id: string;
    issued_at: string;
    expires_at: string;
    nonce: string;
    key_id: string;
    consent_revision: number;
    payload: T;
  };
  signature: string;
}
export interface Assignment {
  task_id: string;
  owner_id: OwnerId;
  start: number;
  end: number;
  offer_id: string;
  offer_revision: number;
}
export interface Action {
  action_id: string;
  owner_id: OwnerId;
  task_id: string;
  label: string;
  start: number;
  end: number;
  date: string;
  timezone: string;
  adapter: "local-calendar";
  event_id: string;
  expected_absent: boolean;
  status?: string;
  error?: string;
  etag?: string;
  verified_at?: string;
  remaining_effect?: Json;
}
export interface Proposal {
  proposal_id: string;
  version: number;
  goal_id: string;
  goal_revision: number;
  date: string;
  timezone: string;
  created_at: string;
  expires_at: string;
  tasks: Task[];
  assignments: Assignment[];
  actions: Action[];
  offer_refs: {
    owner_id: OwnerId;
    offer_id: string;
    revision: number;
    consent_revision: number;
    constraint_revision: number;
  }[];
  solver: { status: string; objectives: Json; settings: Json };
  checker: { valid: boolean; checks: Json; errors: Json };
  model_receipt_id: string | null;
  explanation: string | Json;
}
export interface ApprovalPayload {
  proposal_id: string;
  version: number;
  proposal_digest: string;
  manifest_digest: string;
  action_ids: string[];
  constraint_revision: number;
  execution_not_after: string;
  compensation_policy?: "delete-only-unchanged-created-events";
}
export interface ProposalWrapper {
  proposal: Proposal | null;
  proposal_digest?: string;
  manifest_digest?: string;
}
export interface ModelRun {
  receipt_id?: string;
  id?: string;
  provider?: string;
  model?: string;
  status?: string;
  outcome?: string;
  error?: string;
  request_id?: string;
  created_at?: string;
  latency_ms?: number;
  usage?: Json;
  settings?: Json;
  [key: string]: Json | undefined;
}
export interface BrokerState extends ProposalWrapper {
  sample: boolean;
  goal: {
    goal_id: string;
    title?: string;
    description?: string;
    date?: string;
    timezone?: string;
    revision?: number;
    tasks?: Task[];
    [key: string]: Json | Task[] | undefined;
  };
  owners: Owner[];
  offers: Envelope<ReleasePayload>[];
  approvals: Envelope<ApprovalPayload>[];
  state: string;
  actions: Action[];
  model_runs: ModelRun[];
  disclosures: Json[];
  history: Json[];
  revision: number;
  provider: Json;
  planning: { status: string; phase?: string; error?: string | null };
}
export interface Preferences {
  availability_start: number;
  availability_end: number;
  task_ids: string[];
  ask_before_driving: boolean;
  private_note?: string;
  preference_cost?: number;
  revision?: number;
}
export interface CalendarEvent {
  event_id: string;
  summary: string;
  start: number;
  end: number;
  date?: string;
  timezone?: string;
  etag?: string;
  action_id?: string;
  [key: string]: Json | undefined;
}
export interface PrivateCalendarEntry {
  source_id: string;
  title: string;
  start: number;
  end: number;
  date: string;
  timezone: string;
}
export interface OwnerState {
  owner:
    | Owner
    | {
        owner_id: OwnerId;
        name: string;
        role?: string;
        port?: number;
        key_id?: string;
        public_key?: string;
      };
  preferences: Preferences;
  private_calendar: PrivateCalendarEntry[];
  release: Envelope<ReleasePayload> | null;
  consent_revision: number;
  constraint_revision: number;
  proposals: ProposalWrapper[];
  approvals: Envelope<ApprovalPayload>[];
  calendar_events: CalendarEvent[];
  fault: string | { mode: string };
  skills: Json[];
  corrections: Json[];
  coordinator_available?: boolean;
}
export interface ReleasePreview {
  offer?: Offer;
  recipients?: Recipients;
  fields?: string[];
  purpose?: string;
  retention?: string;
  payload?: ReleasePayload;
  constraint_revision?: number;
  consent_revision?: number;
  [key: string]: Json | Offer | Recipients | ReleasePayload | undefined;
}
