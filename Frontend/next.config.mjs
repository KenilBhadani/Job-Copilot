const BACKEND = process.env.BACKEND_URL || "http://localhost:8000";

/** Proxy /api/* to FastAPI so the browser sees one origin (no CORS setup needed). */
export default {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${BACKEND}/api/:path*` }];
  },
};