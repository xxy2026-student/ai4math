/**
 * OpenCode 状态门禁。
 *
 * OpenCode 的 tool.execute.after 把工具参数放在 input.args；output 是工具
 * 结果。write/edit/apply_patch/bash 后统一跑全树门禁，避免补丁或 shell 写入
 * 绕过。Python 优先选择仓库 .venv，兼容 Windows 与 POSIX。
 */
import { existsSync } from "node:fs";
import path from "node:path";

const MUTATING_TOOLS = new Set(["write", "edit", "apply_patch", "bash"]);

export function pythonFor(directory, platform = process.platform) {
  const candidates = [
    path.join(directory, ".venv", "Scripts", "python.exe"),
    path.join(directory, ".venv", "bin", "python"),
  ];
  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  return platform === "win32" ? "python" : "python3";
}

export function shouldGate(input) {
  return MUTATING_TOOLS.has(String(input?.tool ?? "").toLowerCase());
}

export function toolArgs(input) {
  return input?.args && typeof input.args === "object" ? input.args : {};
}

export const Ai4mathGate = async ({ $, directory }) => {
  const python = pythonFor(directory);
  const script = path.join(directory, "verifiers", "hook_gate.py");
  return {
    "tool.execute.after": async (input, _output) => {
      if (!shouldGate(input)) return;
      // Read the current OpenCode event shape deliberately. apply_patch/bash do
      // not expose one reliable target path, hence the full-tree check below.
      const args = toolArgs(input);
      const target = args.filePath ?? args.file_path;
      try {
        await $`${python} ${script} --all --root ${directory}`.cwd(directory).quiet();
      } catch (e) {
        const msg =
          (e?.stderr?.toString?.() ?? "") + (e?.stdout?.toString?.() ?? "");
        throw new Error(
          `[ai4research gate${target ? ` after ${input.tool}: ${target}` : ""}] ` +
            (msg.trim() || "全树门禁退出码非零（检查 Python/虚拟环境）"),
        );
      }
    },
  };
};
