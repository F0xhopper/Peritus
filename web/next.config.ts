import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  turbopack: {
    root: path.join(__dirname),
  },
  async redirects() {
    return [
      // /dashboard is gone — every section of it was a weaker copy of
      // /experts or the sidebar. Kept as a redirect rather than a 404 because
      // it was the post-login target, so live sessions and bookmarks still
      // point at it. Not permanent: the path may be reused later.
      { source: "/dashboard", destination: "/experts", permanent: false },
    ];
  },
};

export default nextConfig;
