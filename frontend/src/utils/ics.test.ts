import { describe, expect, it } from "vitest";
import { buildIcs } from "./ics";
import type { CalendarData } from "../types/api";

describe("buildIcs", () => {
  it("writes all-day and timed entries in the Istanbul time zone", () => {
    const data = {
      events: [{ id: 7, label: "Son başvuru günü", organization: "Örnek Kurum", job_title: "Memur; alımı", date: "2026-12-15", end_date: null, time: "", url: "", evidence: "" }],
      tasks: [{ task_id: 3, title: "KPSS çalış", description: "", date: "2026-12-14", start_time: "19:00", end_time: "20:30" }],
    } as unknown as CalendarData;
    const ics = buildIcs(data, new Date("2026-11-16T10:00:00Z"));

    expect(ics).toContain("DTSTART;VALUE=DATE:20261215");
    expect(ics).toContain("DTEND;VALUE=DATE:20261216");
    expect(ics).toContain("DTSTART;TZID=Europe/Istanbul:20261214T190000");
    expect(ics).toContain("SUMMARY:Son başvuru günü: Örnek Kurum");
    expect(ics).toContain(String.raw`DESCRIPTION:Memur\; alımı`);
    expect(ics.split("BEGIN:VEVENT")).toHaveLength(3);
  });
});
