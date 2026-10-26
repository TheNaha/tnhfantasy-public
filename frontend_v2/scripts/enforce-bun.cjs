const userAgent = process.env.npm_config_user_agent || "";
const isBun = typeof process.versions.bun !== "undefined" || userAgent.startsWith("bun/");

if (!isBun) {
  console.error("");
  console.error("This frontend workspace is bun-only.");
  console.error("Use `bun install`, `bun run dev`, `bun test`, and `bun run build`.");
  console.error(`Detected package manager: ${userAgent || "unknown"}`);
  console.error("");
  process.exit(1);
}
