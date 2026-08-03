/**
 * ai4math 状态门禁插件（OpenCode 适配层）。
 *
 * 与 Claude Code 的 PostToolUse hook 语义等价：write/edit 落盘后调
 * verifiers/gate.py 核验 conjectures/lemmas 的状态纪律；违规时抛错，
 * 拒绝理由原样反馈给模型（文件保留，模型须修正后重写）。
 *
 * 要求系统 PATH 上有 python（gate.py 仅用标准库；验证器重跑自动走 .venv）。
 */
export const Ai4mathGate = async ({ $, directory }) => {
  return {
    "tool.execute.after": async (input, output) => {
      if (input.tool !== "write" && input.tool !== "edit") return;
      const raw = output?.args?.filePath ?? output?.args?.file_path;
      if (!raw) return;
      const norm = String(raw).replace(/\\/g, "/");
      if (!norm.endsWith(".md")) return;
      if (!norm.includes("conjectures/") && !norm.includes("lemmas/")) return;
      try {
        await $`python verifiers/gate.py ${raw}`.cwd(directory).quiet();
      } catch (e) {
        const msg =
          (e?.stderr?.toString?.() ?? "") + (e?.stdout?.toString?.() ?? "");
        throw new Error(
          "[ai4math gate] " +
            (msg.trim() || "gate.py 退出码非零（检查 python 是否在 PATH 上）"),
        );
      }
    },
  };
};
