import { query } from "./_generated/server";

export const siteUrl = query({
  args: {},
  handler: async () => {
    return process.env.CONVEX_SITE_URL ?? null;
  },
});
