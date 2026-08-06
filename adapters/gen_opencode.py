"""从 .claude/ 生成 OpenCode 适配层：.opencode/agents、.opencode/commands、AGENTS.md。

单一事实源：角色与工作流只在 .claude/ 下手改；本脚本把它们翻译成
OpenCode 的格式。改完源文件后重跑：

    python adapters/gen_opencode.py

模型映射（可选）：adapters/opencode.models.json 把 .claude 的模型档位
（opus/sonnet/haiku）映射到 OpenCode 的 provider/model-id，例如
    {"opus": "deepseek/deepseek-reasoner", "sonnet": "deepseek/deepseek-chat"}
没有该文件则不写 model 字段，agent 继承会话默认模型。

（门禁插件 .opencode/plugins/ai4math-gate.js 是手写文件，不由本脚本生成。）
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "runner"))
import loader  # noqa: E402  复用 runner 的 frontmatter 解析

NOTE = "<!-- 由 adapters/gen_opencode.py 生成，勿手改；源文件在 .claude/ 与 CLAUDE.md -->"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("generated ->", os.path.relpath(path, ROOT))


def _prune_generated(directory, expected_names):
    """Remove stale generated Markdown without touching hand-written files."""
    if not os.path.isdir(directory):
        return
    expected = {f"{name}.md" for name in expected_names}
    for filename in os.listdir(directory):
        if not filename.endswith(".md") or filename in expected:
            continue
        path = os.path.join(directory, filename)
        try:
            with open(path, encoding="utf-8-sig") as f:
                generated = NOTE in f.read(1000)
        except OSError:
            generated = False
        if generated:
            os.unlink(path)
            print("removed stale generated ->", os.path.relpath(path, ROOT))


def gen_agents(models):
    roles = loader.load_roles()
    directory = os.path.join(ROOT, ".opencode", "agents")
    _prune_generated(directory, roles)
    for name, r in roles.items():
        meta = r["meta"]
        lines = ["---",
                 "description: " + json.dumps(meta.get("description", name),
                                              ensure_ascii=False),
                 "mode: subagent"]
        tier = meta.get("model")
        if tier in models:
            lines.append("model: " + models[tier])
        lines += ["---", "", NOTE, "", r["prompt"], ""]
        _write(os.path.join(ROOT, ".opencode", "agents", f"{name}.md"),
               "\n".join(lines))


def gen_commands():
    skills = loader.load_skills()
    directory = os.path.join(ROOT, ".opencode", "commands")
    _prune_generated(directory, skills)
    for name, s in skills.items():
        desc = s["meta"].get("description", name)
        text = "\n".join(["---",
                          "description: " + json.dumps(desc, ensure_ascii=False),
                          "---", "", NOTE, "", s["body"], ""])
        _write(os.path.join(ROOT, ".opencode", "commands", f"{name}.md"), text)


def gen_agents_md():
    _write(os.path.join(ROOT, "AGENTS.md"),
           NOTE + "\n\n" + loader.load_claude_md())


def main():
    models_path = os.path.join(ROOT, "adapters", "opencode.models.json")
    models = {}
    if os.path.exists(models_path):
        with open(models_path, encoding="utf-8") as f:
            models = json.load(f)
    gen_agents(models)
    gen_commands()
    gen_agents_md()
    print("完成。OpenCode 用户在仓库目录运行 opencode 即可使用 "
          "/explore 等命令与全部角色。")


if __name__ == "__main__":
    main()
