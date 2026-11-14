import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useEffect, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "../services/api/auth";
import type { Profile, ProfileUpdate } from "../types/api";
import ProfilePage from "./ProfilePage";

let storedProfile: Profile;

function TestAuth({ children }: { children: ReactNode }) {
  const { signIn } = useAuth();

  useEffect(() => {
    void signIn("local-test-key");
  }, [signIn]);

  return children;
}

function renderProfilePage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <TestAuth>
          <ProfilePage />
        </TestAuth>
      </AuthProvider>
    </QueryClientProvider>,
  );
}

describe("ProfilePage", () => {
  beforeEach(() => {
    storedProfile = {
      id: 1,
      degree: "Lisans",
      department: "Bilgisayar Mühendisliği",
      university: "Üniversite",
      kpss_score_type: "P3",
      kpss_p3: 87.6,
      preferred_locations: "Türkiye geneli",
      accepts_shifts: null,
      yds_score: null,
      age: null,
      driver_license: null,
      experience_years: null,
      has_internship: null,
      internship_description: "",
      certificates: "",
      programming_language_evidence: "",
      skills: "",
      notes: "",
      updated_at: null,
    };

    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/auth/check")) {
        return new Response(JSON.stringify({ authenticated: true }), { status: 200 });
      }
      if (url.endsWith("/health")) {
        return new Response(JSON.stringify({
          status: "ok",
          app: "CareerPilot TR API",
          version: "0.4.0",
          demo_mode: false,
        }), { status: 200 });
      }
      if (url.endsWith("/profile") && init?.method === "PUT") {
        const updates = JSON.parse(String(init.body)) as ProfileUpdate;
        storedProfile = { ...storedProfile, ...updates };
      }
      return new Response(JSON.stringify(storedProfile), { status: 200 });
    }));
  });

  afterEach(() => vi.unstubAllGlobals());

  it("saves age and KPSS score changes through the profile API", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.mocked(fetch);
    renderProfilePage();

    await user.click(await screen.findByRole("button", { name: "Profili düzenle" }));
    await user.clear(screen.getByRole("spinbutton", { name: "Yaş" }));
    await user.type(screen.getByRole("spinbutton", { name: "Yaş" }), "24");
    await user.clear(screen.getByRole("spinbutton", { name: "KPSS P3" }));
    await user.type(screen.getByRole("spinbutton", { name: "KPSS P3" }), "87.66");
    await user.click(screen.getByRole("button", { name: "Değişiklikleri kaydet" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Profil güncellendi.");
    expect(storedProfile.age).toBe(24);
    expect(storedProfile.kpss_p3).toBe(87.66);

    const putRequest = fetchMock.mock.calls.find(([, init]) => init?.method === "PUT");
    expect(JSON.parse(String(putRequest?.[1]?.body))).toMatchObject({
      age: 24,
      kpss_p3: 87.66,
    });
  });
});
