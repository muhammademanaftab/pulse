import { v } from "convex/values";
import { internalMutation, internalQuery } from "./_generated/server";

export const insert = internalMutation({
  args: {
    username: v.optional(v.string()),
    eventId: v.optional(v.string()),
    message: v.string(),
    response: v.optional(v.string()),
    timestamp: v.string(),
    ts: v.number(),
    project: v.string(),
    projectPath: v.string(),
    sessionId: v.string(),
    model: v.optional(v.string()),
  },
  handler: async (ctx, args) => {
    // A double-fired Stop hook can send the same turn twice; dedup on eventId.
    const eventId = args.eventId;
    if (eventId) {
      const existing = await ctx.db
        .query("prompts")
        .withIndex("by_event_id", (q) => q.eq("eventId", eventId))
        .first();
      if (existing) return existing._id;
    }
    const id = await ctx.db.insert("prompts", {
      ...args,
      processed: false,
    });
    return id;
  },
});

export const listInRange = internalQuery({
  args: {
    startTs: v.number(),
    endTs: v.number(),
    onlyUnprocessed: v.optional(v.boolean()),
  },
  handler: async (ctx, { startTs, endTs, onlyUnprocessed }) => {
    if (onlyUnprocessed) {
      return await ctx.db
        .query("prompts")
        .withIndex("by_processed_ts", (q) =>
          q.eq("processed", false).gte("ts", startTs).lt("ts", endTs),
        )
        .collect();
    }
    return await ctx.db
      .query("prompts")
      .withIndex("by_ts", (q) => q.gte("ts", startTs).lt("ts", endTs))
      .collect();
  },
});

export const markProcessed = internalMutation({
  args: { ids: v.array(v.id("prompts")) },
  handler: async (ctx, { ids }) => {
    const now = Date.now();
    for (const id of ids) {
      await ctx.db.patch(id, { processed: true, processedAt: now });
    }
    return { count: ids.length };
  },
});
