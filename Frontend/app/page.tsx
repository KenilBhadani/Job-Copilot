"use client";

import { useEffect, useState } from "react";
import { getStats, type Stats } from "@/lib/api";

export default function Home() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    getStats().then(setStats).catch((e) => setError(e.message));
  }, []);

  return (
    <main style={{ padding: 32 }}>
      <h1>Shortlist</h1>
      {error && <p>Can&apos;t reach the backend: {error}</p>}
      {stats && <p>Connected. {stats.jobs} jobs from {stats.companies} companies.</p>}
      {!stats && !error && <p>Connecting…</p>}
    </main>
  );
}