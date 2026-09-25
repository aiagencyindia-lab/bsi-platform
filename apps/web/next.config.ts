import type { NextConfig } from "next";

// A 1,000-product CSV is a few hundred KB; the default Server Action
// body limit is 1 MB.
const config: NextConfig = {
  experimental: { serverActions: { bodySizeLimit: "4mb" } },
};
export default config;
