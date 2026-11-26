export type MatchCategory = "UYGUN" | "POTANSİYEL OLARAK UYGUN" | "UYGUN DEĞİL";
export type RequirementStatus = "met" | "not_met" | "unknown" | "not_required";
export type Tracking = "" | "saved" | "applied" | "awaiting" | "won" | "lost" | "hidden";

export interface Profile {
  id: number;
  degree: string;
  department: string;
  department_aliases: string;
  faculty: string;
  gender: string;
  special_status: string;
  birth_date: string | null;
  military_status: string;
  educations: Array<{ level: string; school: string; department: string; year: string }>;
  experiences: Array<{ organization: string; position: string; start: string; end: string }>;
  experience_state: "" | "none" | "has";
  foreign_language: string;
  preferences: { cities?: string[]; institution_types?: string[]; keywords?: string[]; excluded?: string[] };
  university: string;
  kpss_score_type: string;
  kpss_p3: number | null;
  kpss_scores: Record<string, number>;
  preferred_locations: string;
  accepts_shifts: boolean | null;
  yds_score: number | null;
  ales_score: number | null;
  ales_score_type: "" | "sayisal" | "sozel" | "esit_agirlik";
  ales_year: number | null;
  gpa: number | null;
  age: number | null;
  driver_license: boolean | null;
  experience_years: number | null;
  has_internship: boolean | null;
  internship_description: string;
  certificates: string;
  programming_language_evidence: string;
  skills: string;
  notes: string;
  updated_at: string | null;
}

export type ProfileUpdate = Omit<Profile, "id" | "updated_at">;

export interface Requirement {
  name: string;
  status: RequirementStatus;
  detail: string;
  evidence: string;
}

export interface Verification {
  decision: "eligible" | "not_eligible";
  scope: "job" | "position";
  note: string;
  verified_at: string | null;
  stale: boolean;
  changes: string[];
}

export interface MatchDetail {
  category: MatchCategory;
  reason: string;
  kind: "standard" | "academic";
  data_quality: "full" | "listing_only";
  met_conditions: string[];
  failed_conditions: string[];
  unknown_conditions: string[];
  general_conditions: string[];
  requirements: Requirement[];
  education: { label: string; status: RequirementStatus; basis: string; requirement?: string };
  kpss: {
    score_types: string[];
    minimum_score: number | null;
    candidate_score_type: string;
    candidate_score: number | null;
    status: string;
  };
}

export interface MatchedPosition {
  id: string;
  parent_job_id: number;
  title: string;
  position: string;
  organization: string;
  city: string | null;
  quota: string | null;
  source_url: string | null;
  source_name: string;
  also_listed: Array<{ source_name: string; source_url: string | null }>;
  announcement_date: string | null;
  application_start: string | null;
  application_deadline: string | null;
  days_left: number | null;
  application_status: string;
  is_expired: boolean;
  employment_type: string;
  recruitment_method: string;
  education_requirement: string;
  qualification_codes: string;
  kpss_score_type: string;
  kpss_min_score: number | null;
  location_match: boolean | null;
  tracking: Tracking;
  /** Geçerli kategori: kullanıcının kararı varsa o, yoksa sistemin kararı. */
  category: MatchCategory;
  system_category: MatchCategory;
  verification: Verification | null;
  out_of_preference: boolean;
  ocr_confidence: number | null;
  data_status: "read" | "partial" | "listing_only" | "ocr";
  review_required: boolean;
  cancellation_notice: string;
  basis: { document_title: string; document_url: string; table_row: number } | null;
  written_exam_invite_count?: number | null;
  notes: string;
  first_seen: string | null;
  match: MatchDetail;
}

export interface Opportunity {
  id: number;
  title: string;
  organization: string;
  city: string;
  source_url: string | null;
  source_name: string;
  application_start: string | null;
  application_deadline: string | null;
  application_status: string;
  description: string;
}

export interface MatchResponse {
  counts: Record<MatchCategory | "total" | "education_count", number>;
  jobs: MatchedPosition[];
  education_opportunities: Opportunity[];
  generated_at: string;
}

export interface OfficialDocument {
  id: number;
  title: string;
  url: string;
  status: string;
  error: string;
}

export interface JobEvent {
  id: number;
  job_id: number | null;
  kind: string;
  label: string;
  date: string;
  end_date: string | null;
  time: string;
  evidence: string;
  url: string;
  source: "auto" | "user" | "result" | "account" | "ylsy";
  user_edited: boolean;
  verified: boolean;
  previous_date: string | null;
  /** Tarihin nasıl bulunduğu: listing | label | sentence | user */
  method?: string;
  confidence?: string;
}

export interface CalendarEvent extends JobEvent {
  organization: string;
  job_title: string;
  category: MatchCategory;
  tracking: Tracking;
  cancelled: boolean;
  /** Sonuç duyurusu, hesap sınavı ve YLSY tarihleri düzenlenemez. */
  readonly?: boolean;
}

export interface TaskOccurrence {
  task_id: number;
  title: string;
  description: string;
  date: string;
  start_time: string;
  end_time: string;
  priority: "low" | "normal" | "high";
  recurrence: string;
  done: boolean;
}

export interface CalendarData {
  events: CalendarEvent[];
  tasks: TaskOccurrence[];
}

export interface TaskInput {
  title: string;
  description: string;
  task_date: string;
  start_time: string;
  end_time: string;
  priority: "low" | "normal" | "high";
  recurrence: "none" | "daily" | "weekly" | "weekdays" | "monthly";
  weekdays: number[];
  until: string | null;
}

export interface Task extends TaskInput {
  id: number;
  completed_dates: string[];
}

export interface EventInput {
  kind: string;
  event_date: string;
  end_date?: string | null;
  event_time?: string;
  title?: string;
  evidence?: string;
  url?: string;
}

export interface JobDetail {
  id: number;
  title: string;
  organization: string;
  source_name: string;
  source_url: string | null;
  description: string;
  document_review: { status: string; error: string; documents: OfficialDocument[] } | null;
  tracking: Tracking;
  notes: string;
  has_pdf: boolean;
  events: JobEvent[];
  muted: boolean;
  results: ResultStatus;
  account_records: AccountRecord[];
  job_verification: Verification | null;
  positions: MatchedPosition[];
}

export interface Source {
  name: string;
  url: string;
  description: string;
  status: string;
  job_count: number;
  last_sync: string | null;
  last_success: string | null;
  last_found: number;
  last_created: number;
  last_updated: number;
  last_unchanged: number;
  failed_items: Array<{ job_id: number; title: string; url: string; scanned: boolean; reason: string }>;
  last_detail_failed: number;
  pages_checked: number;
  last_error: string | null;
  error_kind: string | null;
  error_kind_label: string | null;
  last_origin: string | null;
  last_success_origin: string | null;
  days_since_success: number | null;
  stale: boolean;
  access_hint: string | null;
  read_from_other_source: number;
}

export interface StorageStatus { backend: string; durable: boolean; warning: string | null }

export interface SystemStatus {
  storage: StorageStatus;
  scan_origin: string;
  auto_scan_hours: number | null;
  last_scan_at: string | null;
  ocr_enabled: boolean;
  timezone: string;
}

export interface DiagnoseReport {
  location: { country: string; colo: string };
  origin: string;
  storage: StorageStatus;
  browser: { ok: boolean; detail: string };
  targets: Array<{
    name: string; url: string; host: string; verdict: string;
    dns?: { ok: boolean; seconds: number }; tcp?: { ok: boolean; seconds: number }; tls?: { ok: boolean; seconds: number };
    http?: { ok: boolean; seconds: number; status?: number };
  }>;
}

export interface SyncStatus {
  running: boolean;
  started?: boolean;
  trigger: string | null;
  started_at: string | null;
  finished_at: string | null;
  progress: { source: string; current: number; total: number } | null;
  error: string | null;
  report: {
    success: boolean;
    results: Record<string, { source: string; status: string; found: number; imported: number; updated: number; detail_failed: number; error: string | null }>;
    notifications?: { created: number };
  } | null;
}

export interface AppNotification {
  id: number;
  kind: string;
  job_id: number | null;
  category: string;
  title: string;
  body: string;
  created_at: string | null;
  read: boolean;
}

export interface NotificationList {
  unread: number;
  items: AppNotification[];
}

export interface NotificationSettings {
  notify_categories: MatchCategory[];
  only_preferred_locations: boolean;
  deadline_reminder_days: number;
  remind_application_start: boolean;
  remind_deadline: boolean;
  remind_exam: boolean;
  remind_result: boolean;
  remind_other: boolean;
  notify_results: boolean;
  notify_announcements: boolean;
  email_enabled: boolean;
  email_to: string;
  telegram_enabled: boolean;
  telegram_chat_id: string;
  email_available?: boolean;
  telegram_available?: boolean;
}


export interface ResultAnnouncement {
  id: number;
  job_id: number;
  title: string;
  url: string;
  document_url: string | null;
  kind: string;
  kind_label: string;
  published_date: string | null;
  found_at: string;
  match_status: "matched" | "needs_review";
  user_confirmed: boolean;
  reasons: string[];
  organization?: string;
  job_title?: string;
  tracking?: Tracking;
}

export type ResultCode = "found" | "needs_review" | "closed" | "waiting" | "pending" | "no_source" | "error" | "not_due" | "not_found";

export interface ResultStatus {
  status: ResultCode;
  message: string;
  announcements: ResultAnnouncement[];
  source_url: string | null;
  manual_url: string | null;
  last_checked_at: string | null;
  last_success_at: string | null;
  account_only: boolean;
  expected_date: string | null;
}

export interface ResultsOverview {
  announcements: ResultAnnouncement[];
  tracked: Array<{ job_id: number; organization: string; job_title: string; tracking: Tracking; status: ResultCode; message: string; last_checked_at: string | null; source_url: string | null; expected_date: string | null }>;
  tracking_counts: Record<string, number>;
  last_checked_at: string | null;
}

export interface AccountRecord {
  id: number;
  section: "applications" | "cancelled" | "exams";
  section_label: string;
  title: string;
  organization: string;
  status: string;
  result: string;
  applied_date: string | null;
  exam_date: string | null;
  exam_time: string;
  exam_place: string;
  job_id: number | null;
  job_title: string | null;
  match_status: "matched" | "needs_review" | "unmatched" | "confirmed";
  last_seen_at: string;
}

export interface AccountOverview {
  verified: boolean;
  last_success: string | null;
  last_attempt: { at: string; error?: string | null; sections: Record<string, { status: string; count?: number; detail?: string }>; menu?: string[] } | null;
  running: boolean;
  message: string;
  can_import_here: boolean;
  cannot_import_reason: string;
  items: AccountRecord[];
}

export interface YlsyAnnouncement {
  id: number;
  title: string;
  url: string;
  category: string;
  category_label: string;
  published_date: string | null;
  first_seen_at: string;
  cycle: number | null;
  summary: string;
  attachments: Array<{ title: string; url: string }>;
  backfill: boolean;
}

export interface YlsyCheck { name: string; status: "met" | "not_met" | "unknown" | "info"; detail: string; evidence: string }

export interface YlsyField {
  group_code: string; area_code: string; group: string; institution: string; field: string; quota: string; level: string;
  countries: string; document: string; ales_types: string[]; ales_type_status: "met" | "not_met" | "unknown"; age_status: "met" | "not_met" | "unknown";
}

export interface YlsyOverview {
  source: { name: string; url: string };
  sync: { status: string; new: number; checked_at: string; error: string | null; last_success: string | null } | null;
  notice: string;
  latest_cycle: number | null;
  current_year_announced: boolean;
  announcements: YlsyAnnouncement[];
  assessment: {
    available: boolean; message: string; cycle?: number | null; guide_title?: string; guide_url?: string; guide_pdf?: string | null;
    guide_date?: string | null; decision?: "eligible" | "not_eligible" | "needs_verification" | "no_fields"; checks?: YlsyCheck[];
    department_codes?: string[]; fields?: YlsyField[]; application?: { start: string; end: string; evidence: string } | null; read_errors?: string[];
  };
}
