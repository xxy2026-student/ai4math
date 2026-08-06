/** Cross-platform Claude Code hook launcher.
 *
 * Claude Code itself requires Node, so this avoids assuming that POSIX systems
 * provide a `python` alias. The Python hook then re-execs into the repository
 * virtual environment when one exists.
 */
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";

const root = process.env.CLAUDE_PROJECT_DIR || process.cwd();
const candidates = [
  path.join(root, ".venv", "Scripts", "python.exe"),
  path.join(root, ".venv", "bin", "python"),
];
const python = candidates.find(existsSync) ||
  (process.platform === "win32" ? "python" : "python3");
const script = path.join(root, "verifiers", "hook_gate.py");
const input = readFileSync(0);
const result = spawnSync(python, [script], {
  cwd: root,
  env: process.env,
  input,
  encoding: "utf8",
  windowsHide: true,
});

if (result.stdout) process.stdout.write(result.stdout);
if (result.stderr) process.stderr.write(result.stderr);
if (result.error) {
  process.stderr.write(`[hook_gate launcher] ${result.error.message}\n`);
  process.exit(2);
}
process.exit(result.status ?? 2);
