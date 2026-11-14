import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { MatchedJob } from "../../types/api";
import { MatchCard } from "./MatchCard";

const sbbJob: MatchedJob = {
  id: "91",
  parent_job_id: 91,
  title: "6 Memur Alacak",
  position: "6 Memur Alacak",
  organization: "Şile Belediye Başkanlığı",
  city: null,
  quota: "6",
  source_url: "https://kamuilan.sbb.gov.tr/",
  source_name: "SBB Kamu İlanları",
  announcement_date: null,
  application_start: "2026-11-09",
  application_deadline: "2026-11-13",
  application_status: "Başvuru Açık",
  is_expired: false,
  employment_type: "Memur",
  recruitment_method: "Kaynakta belirtilmedi",
  education_requirement: "",
  qualification_codes: "",
  kpss_score_type: "",
  kpss_min_score: null,
  description: "6 Memur Alacak",
  match: {
    category: "POTANSİYEL OLARAK UYGUN",
    reason: "İlan koşulları değerlendirilmelidir.",
    met_conditions: [],
    failed_conditions: [],
    unknown_conditions: [],
    general_conditions: [],
    requirements: [],
    education: {
      requirement: "",
      computer_engineering: "",
      basis: "",
    },
    kpss: {
      score_types: [],
      minimum_score: null,
      candidate_score_type: "P3",
      candidate_score: 87.6,
      status: "Bilinmiyor",
    },
  },
};

describe("MatchCard", () => {
  it("renders SBB job fields independently and links to the stable source index", () => {
    render(<MatchCard job={sbbJob} />);

    expect(screen.getByRole("heading", { name: "6 Memur Alacak" })).toBeInTheDocument();
    expect(screen.getByText("Şile Belediye Başkanlığı")).toBeInTheDocument();
    expect(screen.getByText("İstihdam türü · Memur")).toBeInTheDocument();
    expect(screen.getByText("Alım yöntemi · Kaynakta belirtilmedi")).toBeInTheDocument();
    expect(screen.getByText("Kontenjan · 6")).toBeInTheDocument();
    expect(screen.getByText("İlan tarihi · Kaynakta bulunamadı")).toBeInTheDocument();
    expect(screen.getByText("Başvuru başlangıcı · 09 Kas 2026")).toBeInTheDocument();
    expect(screen.getByText("Son başvuru · 13 Kas 2026")).toBeInTheDocument();
    expect(screen.getByText("Kaynakta bulunamadı")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Resmî SBB ilan listesine git" }),
    ).toHaveAttribute("href", "https://kamuilan.sbb.gov.tr/");
    expect(
      screen.getByText(/detay bağlantıları şu anda doğrulanamıyor/i),
    ).toBeInTheDocument();
  });

  it("shows scanned official annexes, position rows, and separate exam-call ranking", () => {
    const { container } = render(
      <MatchCard
        job={{
          ...sbbJob,
          document_review: {
            status: "complete",
            error: "",
            checked_at: "2026-11-14T10:00:00",
            documents: [
              {
                id: 8,
                title: "Tablo 1: Başvuru Şartları",
                url: "https://kariyerkapisi.gov.tr/Ups/Evraklar/Tablo1.pdf",
                status: "read",
                content_hash: "sha256",
                parsed_content_hash: "sha256",
                error: "",
                checked_at: "2026-11-14T10:00:00",
                positions: [
                  {
                    row_index: 4,
                    position_title: "Bilgisayar Mühendisliği",
                    education_requirement: "Bilgisayar Mühendisliği ve eşdeğer programlar",
                    quota: "2",
                    kpss_score_type: "P3",
                    kpss_min_score: 70,
                    city: "Ankara (2)",
                    qualification_codes: "",
                    written_exam_invite_text: "Her pozisyon için 5 katına kadar.",
                    written_exam_invite_count: 5,
                  },
                ],
              },
            ],
          },
        }}
      />,
    );

    expect(container.querySelector(".document-review")).toHaveTextContent("Ana ilan şartları");
    expect(screen.getByText("Ek belgeden çıkarılan pozisyonlar")).toBeInTheDocument();
    expect(screen.getByText(/Kabul edilen öğrenim:/)).toBeInTheDocument();
    expect(container.querySelector(".document-position")).toHaveTextContent("KPSS: P3");
    expect(container.querySelector(".document-position")).toHaveTextContent("taban 70");
    expect(screen.getByText(/Yazılı sınava çağrı sıralaması/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /İncelenen resmî belgeyi aç/ }),
    ).toHaveAttribute("href", "https://kariyerkapisi.gov.tr/Ups/Evraklar/Tablo1.pdf");
  });
});
