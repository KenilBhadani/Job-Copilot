export type Profile = { skills: string[]; years: number | null; headline: string | null };

export type Match = {
  id: string; company: string; title: string; location: string; remote: boolean;
  url: string; posted_at: string | null; source: string; snippet: string;
  score: number; why: string;
  required_matched: string[]; required_missing: string[];
  preferred_matched: string[]; preferred_missing: string[];
};

export type MatchResponse = {
  profile: Profile; results: Match[]; total_jobs: number; considered: number;
};

export type Stats = { jobs: number; companies: number; last_sync: string | null; llm: boolean };

export type SyncResponse = {
  report: { company: string; ok: boolean; jobs?: number; error?: string }[];
  jobs: number; companies: number; last_sync: string | null;
};

export type MatchRequest = {
  resume_text: string;
  skills?: string[];
  experience_years?: number | null;
  locations: string[];
  // include_remote: boolean;
  remote_only: boolean;
  role_keywords: string[];
  use_llm: boolean;
};

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    let detail = `Request failed (${res.status})`;
    try { detail = (await res.json()).detail ?? detail; } catch { /* keep default */ }
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return res.json();
}

export const getStats = () => request<Stats>("/api/stats");
export const syncJobs = () => request<SyncResponse>("/api/sync", { method: "POST" });

export const matchJobs = (body: MatchRequest) =>
  request<MatchResponse>("/api/match", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });

export async function uploadResume(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  return (await request<{ text: string }>("/api/resume/upload", { method: "POST", body: form })).text;
}