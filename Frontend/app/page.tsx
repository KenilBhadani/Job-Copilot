"use client";

import { useEffect, useRef, useState } from "react";
import JobRow from "@/components/JobRow";
import {
  getStats, matchJobs, syncJobs, uploadResume,
  type MatchResponse, type Stats, type SyncResponse,
} from "@/lib/api";

const list = (s: string) => s.split(",").map((x) => x.trim()).filter(Boolean);

export default function Home() {
  const [resume, setResume] = useState("");
  const [locations, setLocations] = useState("Bengaluru");
  const [roles, setRoles] = useState("");
  const [years, setYears] = useState("");
  const [includeRemote, setIncludeRemote] = useState(true);
  const [remoteOnly, setRemoteOnly] = useState(false);

  const [skills, setSkills] = useState<string[] | null>(null); // null = not edited yet
  const [newSkill, setNewSkill] = useState("");
  const [data, setData] = useState<MatchResponse | null>(null);
  const [stats, setStats] = useState<Stats | null>(null);
  const [syncReport, setSyncReport] = useState<SyncResponse | null>(null);
  const [busy, setBusy] = useState<"match" | "sync" | "upload" | null>(null);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => { getStats().then(setStats).catch(() => setError("Can't reach the backend. Is it running on port 8000?")); }, []);

  async function run(skillsOverride: string[] | null) {
    setBusy("match"); setError("");
    try {
      const res = await matchJobs({
        resume_text: resume,
        skills: skillsOverride ?? undefined,
        experience_years: years ? Number(years) : null,
        locations: list(locations),
        include_remote: includeRemote,
        remote_only: remoteOnly,
        role_keywords: list(roles),
        use_llm: true,
      });
      setData(res);
      setSkills(res.profile.skills);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }

  async function sync() {
    setBusy("sync"); setError("");
    try {
      const res = await syncJobs();
      setSyncReport(res);
      setStats(await getStats());
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(null); }
  }

  async function onFile(file: File | undefined) {
    if (!file) return;
    setBusy("upload"); setError("");
    try { setResume(await uploadResume(file)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(null); if (fileRef.current) fileRef.current.value = ""; }
  }

  function changeSkills(next: string[]) { setSkills(next); run(next); }
  function addSkill() {
    const s = newSkill.trim();
    if (!s || skills?.some((k) => k.toLowerCase() === s.toLowerCase())) { setNewSkill(""); return; }
    setNewSkill(""); changeSkills([...(skills ?? []), s]);
  }

  const noJobs = stats !== null && stats.jobs === 0;
  const failed = syncReport?.report.filter((r) => !r.ok) ?? [];

  return (
    <div className="shell">
      <aside className="panel">
        <h1 className="brand">Shortlist</h1>
        <p className="lede">Paste your resume. See who is hiring for the skills you already have.</p>

        <label className="field">
          <span>Your resume or skills</span>
          <textarea value={resume} onChange={(e) => setResume(e.target.value)} rows={11}
            placeholder="Paste your resume text here, or a few lines about what you build and the tools you use." />
        </label>
        <div className="row">
          <input ref={fileRef} type="file" accept="application/pdf" hidden
                 onChange={(e) => onFile(e.target.files?.[0])} />
          <button className="btn ghost" type="button" onClick={() => fileRef.current?.click()}
                  disabled={busy !== null}>
            {busy === "upload" ? "Reading PDF…" : "Upload a PDF"}
          </button>
        </div>

        <label className="field">
          <span>Locations</span>
          <input value={locations} onChange={(e) => setLocations(e.target.value)}
                 placeholder="Bengaluru, Hyderabad, Pune" />
        </label>
        <label className="check">
          <input type="checkbox" checked={includeRemote} disabled={remoteOnly}
                 onChange={(e) => setIncludeRemote(e.target.checked)} />
          Include remote roles
        </label>
        <label className="check">
          <input type="checkbox" checked={remoteOnly} onChange={(e) => setRemoteOnly(e.target.checked)} />
          Remote only
        </label>
        <div className="two">
          <label className="field">
            <span>Target roles</span>
            <input value={roles} onChange={(e) => setRoles(e.target.value)} placeholder="AI engineer, backend" />
          </label>
          <label className="field narrow">
            <span>Years of experience</span>
            <input value={years} inputMode="numeric" onChange={(e) => setYears(e.target.value.replace(/\D/g, ""))}
                   placeholder="auto" />
          </label>
        </div>

        <button className="btn primary" onClick={() => run(null)}
                disabled={busy !== null || resume.trim().length < 30 || noJobs}>
          {busy === "match" ? "Matching…" : "Find matching jobs"}
        </button>
        {noJobs && <p className="hint">Pull job postings first, then match.</p>}
      </aside>

      <main className="results">
        <div className="topbar">
          <p className="meta">
            {stats
              ? stats.jobs > 0
                ? `${stats.jobs} open roles from ${stats.companies} companies`
                : "No job postings loaded yet"
              : "Connecting…"}
            {stats?.last_sync ? `, updated ${new Date(stats.last_sync).toLocaleString()}` : ""}
          </p>
          <button className="btn ghost" onClick={sync} disabled={busy !== null}>
            {busy === "sync" ? "Pulling jobs…" : noJobs ? "Pull job postings" : "Refresh jobs"}
          </button>
        </div>

        {error && <p className="alert" role="alert">{error}</p>}
        {failed.length > 0 && (
          <p className="alert soft">
            {failed.length} {failed.length === 1 ? "company" : "companies"} could not be loaded:{" "}
            {failed.map((f) => `${f.company} (${f.error})`).join(", ")}. Check the slugs in
            Backend/companies.yaml.
          </p>
        )}

        {skills && (
          <section className="skills" aria-label="Skills read from your resume">
            <h2>Skills we found</h2>
            <p className="hint">Remove or add skills and the results update.</p>
            <ul className="chips">
              {skills.map((s) => (
                <li key={s} className="chip">
                  {s}
                  <button aria-label={`Remove ${s}`} onClick={() => changeSkills(skills.filter((k) => k !== s))}>×</button>
                </li>
              ))}
              <li>
                <input className="chip-input" value={newSkill} placeholder="Add a skill"
                       onChange={(e) => setNewSkill(e.target.value)}
                       onKeyDown={(e) => e.key === "Enter" && addSkill()} />
              </li>
            </ul>
            {data?.profile.headline && <p className="hint">Reads as: {data.profile.headline}</p>}
          </section>
        )}

        {data && (
          <>
            <h2 className="count">
              {data.results.length > 0
                ? `Top ${data.results.length} of ${data.considered} roles that fit your filters`
                : data.total_jobs === 0 ? "No jobs to match against yet"
                : "No roles match these filters"}
            </h2>
            {data.results.length === 0 && data.total_jobs > 0 && (
              <p className="hint">Try adding more locations, turning on remote roles, or clearing the experience field.</p>
            )}
            <ol className="jobs">
              {data.results.map((j) => <JobRow key={j.id} job={j} />)}
            </ol>
          </>
        )}

        {!data && !error && (
          <div className="empty">
            <h2>Start with your resume</h2>
            <p>
              {noJobs
                ? "First pull job postings from the companies listed in Backend/companies.yaml, then paste your resume on the left."
                : "Paste your resume on the left and choose where you want to work. Roles appear here, ranked by how many of their required skills you already have."}
            </p>
          </div>
        )}
      </main>
    </div>
  );
}