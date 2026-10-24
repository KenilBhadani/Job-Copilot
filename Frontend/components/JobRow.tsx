import type { Match } from "@/lib/api";
import SkillStrip from "./SkillStrip";

export default function JobRow({ job }: { job: Match }) {
  return (
    <li className="job">
      <div className="fit" aria-label={`Fit score ${job.score} out of 100`}>
        <span className="fit-num">{job.score}</span>
        <span className="fit-label">fit</span>
      </div>
      <div className="job-main">
        <h3 className="job-title">{job.title}</h3>
        <p className="job-where">
          <strong>{job.company}</strong>
          <span>{job.location || "Location not listed"}{job.remote ? " (remote friendly)" : ""}</span>
        </p>
        <SkillStrip matched={job.required_matched} missing={job.required_missing} />
        <p className="job-why">{job.why}</p>
      </div>
      <a className="btn ghost" href={job.url} target="_blank" rel="noopener noreferrer">
        View posting
      </a>
    </li>
  );
}