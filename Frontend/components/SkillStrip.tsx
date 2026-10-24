/** One segment per required skill: solid = you have it, outlined = gap. */
export default function SkillStrip({ matched, missing }: { matched: string[]; missing: string[] }) {
  const total = matched.length + missing.length;
  if (total === 0) return null;
  return (
    <div>
      <div className="strip" role="img"
           aria-label={`You match ${matched.length} of ${total} required skills`}>
        {matched.map((s) => <span key={s} className="seg have" title={`You have: ${s}`} />)}
        {missing.map((s) => <span key={s} className="seg gap" title={`Missing: ${s}`} />)}
      </div>
      <div className="strip-labels">
        {matched.map((s) => <span key={s} className="tag have">{s}</span>)}
        {missing.map((s) => <span key={s} className="tag gap">{s}</span>)}
      </div>
    </div>
  );
}