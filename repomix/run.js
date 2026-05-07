#!/usr/bin/env node
// run.js — thin wrapper around the local repomix binary
// Usage: node run.js [repomix args...]
// Example: node run.js --output out.xml --style xml ~/projects/my-app

const { execFileSync } = require("child_process");
const path = require("path");

const repomix = path.join(__dirname, "node_modules", ".bin", "repomix");

try {
  execFileSync(repomix, process.argv.slice(2), { stdio: "inherit" });
} catch (err) {
  process.exit(err.status ?? 1);
}