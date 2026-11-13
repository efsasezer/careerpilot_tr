export type MatchCategory =
  | "UYGUN"
  | "POTANSİYEL OLARAK UYGUN"
  | "UYGUN DEĞİL";

export interface Profile {
  id: number;
  degree: string;
  department: string;
  university: string;
  kpss_score_type: string;
  kpss_p3: number | null;
  preferred_locations: string;
  accepts_shifts: boolean | null;
  yds_score: number | null;
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

export interface MatchDetail {
  category: MatchCategory;
  reason: string;
  met_conditions: string[];
  failed_conditions: string[];
  unknown_conditions: string[];
  general_conditions: string[];
  requirements: string[];
  education: {
    requirement: string;
    computer_engineering: string;
    basis: string;
  };
  kpss: {
    score_types: string[];
    minimum_score: number | null;
    candidate_score_type: string;
    candidate_score: number | null;
    status: string;
  };
}

export interface MatchedJob {
  id: string;
  parent_job_id: number;
  title: string;
  position: string;
  organization: string;
  city: string | null;
  quota: string | null;
  source_url: string | null;
  source_name: string;
  application_start: string | null;
  application_deadline: string | null;
  application_status: string;
  is_expired: boolean;
  recruitment_method: string;
  education_requirement: string;
  qualification_codes: string;
  kpss_score_type: string;
  kpss_min_score: number | null;
  description: string;
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
  category: string;
  description: string;
}

export interface MatchCounts {
  total: number;
  UYGUN: number;
  "POTANSİYEL OLARAK UYGUN": number;
  "UYGUN DEĞİL": number;
  education_count: number;
}

export interface MatchResponse {
  profile: Record<string, unknown>;
  counts: MatchCounts;
  jobs: MatchedJob[];
  education_opportunities: Opportunity[];
}

export interface Source {
  name: string;
  url: string;
  description: string;
  status: string;
  job_count: number;
  last_sync: string | null;
  last_found: number;
  last_created: number;
  last_updated: number;
  last_error: string | null;
}

export interface Job {
  id: number;
  sector: "public" | "private";
  title: string;
  organization: string;
  category: string;
  city: string;
  source_url: string;
  source_name: string;
  description: string;
  skills: string;
  kpss_score_type: string;
  kpss_min_score: number | null;
  education_requirement: string;
  qualification_codes: string;
  application_start: string | null;
  application_deadline: string | null;
  quota: string;
  recruitment_method: string;
  is_employment: boolean;
  status: string;
  notes: string;
  created_at: string | null;
  updated_at: string | null;
}

export interface SkillAnalytics {
  category: string;
  job_count: number;
  skills: Array<{ skill: string; count: number; percentage: number }>;
}

export interface Health {
  status: string;
  app: string;
  version: string;
  demo_mode: boolean;
}
