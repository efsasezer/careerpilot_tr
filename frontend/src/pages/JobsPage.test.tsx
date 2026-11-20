import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import JobsPage from "./JobsPage";
import type { MatchedPosition, MatchCategory } from "../types/api";

function position(jobId: number, organization: string, category: MatchCategory, extra: Partial<MatchedPosition> = {}): MatchedPosition {
  return {
    id: String(jobId), parent_job_id: jobId, title: `${organization} ilanı`, position: `${organization} pozisyonu`, organization,
    city: null, quota: null, source_url: null, source_name: "SBB Kamu İlanları", also_listed: [], announcement_date: null,
    application_start: null, application_deadline: "2099-01-10", days_left: 5, application_status: "Başvuru Açık", is_expired: false,
    employment_type: "", recruitment_method: "", education_requirement: "", qualification_codes: "", kpss_score_type: "P3",
    kpss_min_score: 70, location_match: null, tracking: "", category, system_category: category, verification: null, out_of_preference: false, ocr_confidence: null, data_status: "read", review_required: false, cancellation_notice: "", basis: null, notes: "", first_seen: null,
    match: {
      category, reason: "gerekçe", kind: "standard", data_quality: "full", met_conditions: [], failed_conditions: [], unknown_conditions: [],
      general_conditions: [], requirements: [{ name: "Eğitim", status: category === "UYGUN" ? "met" : "not_met", detail: `${organization} eğitim gerekçesi`, evidence: "" }],
      education: { label: "", status: "met", basis: "" },
      kpss: { score_types: ["P3"], minimum_score: 70, candidate_score_type: "P3", candidate_score: 80, status: "met" },
    },
    ...extra,
  };
}

const jobs = [
  position(1, "Uygun Kurum", "UYGUN"),
  position(2, "Başka Kurum", "UYGUN DEĞİL"),
  position(3, "Gizli Kurum", "UYGUN", { tracking: "hidden" }),
  position(4, "Kayıtlı Kurum", "UYGUN DEĞİL", { tracking: "saved" }),
];

vi.mock("../services/api/hooks", () => {
  const mutation = () => ({ mutate: () => undefined, isPending: false, error: null });
  return {
    useMatches: () => ({ data: { jobs, education_opportunities: [] }, isLoading: false, error: null }),
    useSetVerification: mutation,
    useClearVerification: mutation,
  };
});

describe("JobsPage", () => {
  it("shows a manually verified listing under its chosen category", async () => {
    jobs.push(position(5, "Elle Kurum", "POTANSİYEL OLARAK UYGUN", {
      category: "UYGUN",
      verification: { decision: "eligible", scope: "job", note: "", verified_at: null, stale: false, changes: [] },
    }));
    render(<MemoryRouter><JobsPage /></MemoryRouter>);

    expect(screen.getByRole("tab", { name: /^Uygun 2$/ })).toBeInTheDocument();
    expect(screen.getByText("Elle doğrulandı")).toBeInTheDocument();
    expect(screen.getByText("Sistem: Doğrulanmalı · Siz: Uygun")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /Doğrulanmalı/ }));
    expect(screen.queryByText("Elle Kurum pozisyonu")).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: /^Uygun 2$/ }));
    expect(screen.getByText("Elle Kurum pozisyonu")).toBeInTheDocument();
    jobs.pop();
  });

  it("shows suitable listings first and hides the ones the user dismissed", async () => {
    render(<MemoryRouter><JobsPage /></MemoryRouter>);

    expect(screen.getByRole("tab", { name: /^Uygun 1$/ })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByText("Uygun Kurum pozisyonu")).toBeInTheDocument();
    expect(screen.getByText("Uygun Kurum eğitim gerekçesi")).toBeInTheDocument();
    expect(screen.queryByText("Gizli Kurum pozisyonu")).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: /Uygun değil/ }));
    expect(screen.getByText("Başka Kurum pozisyonu")).toBeInTheDocument();

    await userEvent.type(screen.getByPlaceholderText(/Kurum, pozisyon/), "kayıtlı");
    expect(screen.queryByText("Başka Kurum pozisyonu")).not.toBeInTheDocument();
    expect(screen.getByText("Kayıtlı Kurum pozisyonu")).toBeInTheDocument();
  });

  it("lists only saved or applied listings on the tracking page", () => {
    render(<MemoryRouter><JobsPage mode="tracked" /></MemoryRouter>);

    expect(screen.getByText("Kayıtlı Kurum pozisyonu")).toBeInTheDocument();
    expect(screen.queryByText("Uygun Kurum pozisyonu")).not.toBeInTheDocument();
  });
});
