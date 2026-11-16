import { describe, expect, it } from "vitest";
import { deadlineLabel, groupByJob, sortGroups } from "./format";
import type { MatchedPosition, MatchCategory } from "../types/api";

function position(jobId: number, category: MatchCategory, deadline: string | null = null): MatchedPosition {
  return {
    id: `${jobId}-${category}`, parent_job_id: jobId, title: `İlan ${jobId} — Pozisyon`, position: "Pozisyon",
    organization: "Kurum", application_deadline: deadline, category, match: { category },
  } as MatchedPosition;
}

describe("groupByJob", () => {
  it("collects positions per listing and keeps the best category", () => {
    const groups = groupByJob([
      position(1, "UYGUN DEĞİL"), position(1, "UYGUN"), position(1, "POTANSİYEL OLARAK UYGUN"), position(2, "UYGUN DEĞİL"),
    ]);
    expect(groups).toHaveLength(2);
    expect(groups[0]).toMatchObject({ jobId: 1, title: "İlan 1", category: "UYGUN", suitableCount: 2 });
    expect(groups[0].primary.match.category).toBe("UYGUN");
    expect(groups[1].suitableCount).toBe(0);
  });

  it("sorts by relevance first, then by the nearest deadline", () => {
    const groups = groupByJob([
      position(1, "UYGUN DEĞİL", "2026-01-01"), position(2, "UYGUN", "2026-03-01"), position(3, "UYGUN", "2026-02-01"),
    ]);
    expect(sortGroups(groups, "relevance").map((group) => group.jobId)).toEqual([3, 2, 1]);
    expect(sortGroups(groups, "deadline").map((group) => group.jobId)).toEqual([1, 3, 2]);
  });
});

describe("deadlineLabel", () => {
  it("describes the remaining time in plain words", () => {
    expect(deadlineLabel(0, "Başvuru Açık")).toBe("Bugün son gün");
    expect(deadlineLabel(5, "Başvuru Açık")).toBe("5 gün kaldı");
    expect(deadlineLabel(12, "Başvuru Başlamadı")).toBe("Henüz açılmadı");
    expect(deadlineLabel(null, "Başvuru Sona Erdi")).toBe("Süresi doldu");
  });
});
