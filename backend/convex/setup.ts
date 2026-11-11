import { query } from "./_generated/server";

// Returns the deployment's public HTTP Actions URL (the `.convex.site` domain).
// skills/setup/install.py calls `npx convex run setup:siteUrl` to learn the exact
// URL the capture hook must POST to, instead of guessing it from the .cloud URL.
export const siteUrl = query({
  args: {},
  handler: async () => {
    return process.env.CONVEX_SITE_URL ?? null;
  },
});
