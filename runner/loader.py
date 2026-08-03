"""加载框架定义：CLAUDE.md、.claude/agents/*.md（角色）、.claude/skills/*/SKILL.md（工作流）。

单一事实源原则：runner 不自带任何提示词，全部读 Claude Code 用的同一套文件——
两种驱动方式跑的是同一个大脑，改提示词只改一处。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verifiers"))
from gate import parse_frontmatter  # noqa: E402


def _split(text):
    """返回 (frontmatter dict, 正文)；无 frontmatter 时 ({}, 全文)。"""
    meta = parse_frontmatter(text)
    if meta is None:
        return {}, text
    m = re.search(r"\n---\s*(\n|$)", text[3:])
    return meta, text[3 + m.end():]


def _read(path):
    with open(path, encoding="utf-8-sig") as f:
        return f.read()


def load_claude_md():
    p = os.path.join(ROOT, "CLAUDE.md")
    return _read(p) if os.path.exists(p) else ""


def load_roles():
    """{name: {"meta": frontmatter, "prompt": 正文}}"""
    roles = {}
    d = os.path.join(ROOT, ".claude", "agents")
    if not os.path.isdir(d):
        return roles
    for fn in sorted(os.listdir(d)):
        if fn.endswith(".md"):
            meta, body = _split(_read(os.path.join(d, fn)))
            roles[meta.get("name") or fn[:-3]] = {"meta": meta, "prompt": body.strip()}
    return roles


def load_skills():
    """{name: {"meta": frontmatter, "body": 正文}}"""
    skills = {}
    d = os.path.join(ROOT, ".claude", "skills")
    if not os.path.isdir(d):
        return skills
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name, "SKILL.md")
        if os.path.exists(p):
            meta, body = _split(_read(p))
            skills[meta.get("name") or name] = {"meta": meta, "body": body.strip()}
    return skills


def resolve_prompt(user_input, skills):
    """"/skill args" → 展开 SKILL.md 正文并代入 $ARGUMENTS；其余原样返回。"""
    s = user_input.strip()
    if not s.startswith("/"):
        return user_input
    parts = s[1:].split(None, 1)
    name, args = parts[0], (parts[1] if len(parts) > 1 else "")
    if name not in skills:
        return user_input
    return "执行以下工作流：\n\n" + skills[name]["body"].replace("$ARGUMENTS", args)
