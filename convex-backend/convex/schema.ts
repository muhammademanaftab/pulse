import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export default defineSchema({
  prompts: defineTable({
    username: v.optional(v.string()),
    message: v.string(),
    response: v.optional(v.string()),
    timestamp: v.string(),
    ts: v.number(),
    project: v.string(),
    projectPath: v.string(),
    sessionId: v.string(),
    model: v.optional(v.string()),
    processed: v.boolean(),
    processedAt: v.optional(v.number()),
  })
    .index("by_processed_ts", ["processed", "ts"])
    .index("by_ts", ["ts"]),
});
