const userAgent = process.env.npm_config_user_agent || "";

if (!userAgent.startsWith("npm/")) {
  console.error("");
  console.error("This frontend workspace is npm-only.");
  console.error("Use `npm install`, `npm run dev`, `npm test`, and `npm run build`.");
  console.error(`Detected package manager: ${userAgent || "unknown"}`);
  console.error("");
  process.exit(1);
}
