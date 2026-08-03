"""状态门禁核心（纯函数，仅标准库）。

被两个适配层共用，保证 Claude Code 与通用 API runner 执行同一套纪律：
- verifiers/hook_gate.py —— Claude Code PostToolUse hook 薄壳；
- runner/tools.py —— 通用执行器在 write_file 工具后直接调用。

规则见 CLAUDE.md「铁律」一节。
"""
import os
import re
import subprocess
import sys

ALLOWED = {"open", "numeric-verified", "proved", "refuted"}


def parse_frontmatter(text):
    """最小 YAML 解析：顶层 key: value 与一层嵌套。返回 dict，无 frontmatter 返回 None。"""
    if not text.startswith("---"):
        return None
    m = re.search(r"\n---\s*(\n|$)", text[3:])
    if not m:
        return None
    data, current = {}, None
    for line in text[3:3 + m.start()].splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        mm = re.match(r"^(\s*)([A-Za-z_][\w.-]*):\s*(.*?)\s*$", line)
        if not mm:
            continue
        indent, key, val = mm.groups()
        val = val.strip('"').strip("'")
        if indent and current is not None:
            data[current][key] = val
        elif not indent:
            if val == "":
                data[key] = {}
                current = key
            else:
                data[key] = val
                current = None
    return data


def venv_python(root):
    """仓库 .venv 的解释器（Windows/Unix 皆可），没有则退回当前解释器。"""
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        p = os.path.join(root, ".venv", *rel)
        if os.path.exists(p):
            return p
    return sys.executable


def check_file(path, root="."):
    """检查一个刚被写入的文件是否符合状态纪律。

    返回 (ok, msg)：ok=False 时 msg 是给模型看的拒绝理由。
    不属管辖范围（非 conjectures/lemmas 下的 .md）返回 (True, "")。
    """
    norm = str(path).replace("\\", "/")
    if not norm.endswith(".md"):
        return True, ""
    if "/conjectures/" not in norm and "/lemmas/" not in norm:
        return True, ""
    abspath = path if os.path.isabs(path) else os.path.join(root, path)
    if not os.path.exists(abspath):
        return True, ""

    with open(abspath, encoding="utf-8-sig") as f:
        text = f.read()
    data = parse_frontmatter(text)
    if data is None:
        return False, (f"{norm}: 缺少 YAML frontmatter。conjectures/lemmas 下的文件"
                       "必须带 id/status 元数据（格式见 CLAUDE.md）。")

    status = data.get("status")
    if status not in ALLOWED:
        return False, f"{norm}: status 必须是 {sorted(ALLOWED)} 之一，当前为 {status!r}。"
    if "/lemmas/" in norm and status != "proved":
        return False, (f"{norm}: lemmas/ 下只能放 status: proved 的结果（当前 {status}）；"
                       "未证明的放 conjectures/。")
    if status == "open":
        return True, ""

    if status == "proved":
        audit = data.get("audit")
        if not audit or isinstance(audit, dict):
            return False, (f"{norm}: status: proved 需要 audit 字段指向 skeptic "
                           "审计文件（先跑 /audit）。")
        audit_path = audit if os.path.isabs(audit) else os.path.join(root, audit)
        if not os.path.exists(audit_path):
            return False, f"{norm}: audit 文件不存在: {audit}"
        return True, ""

    # numeric-verified / refuted：重跑验证器核验
    verify = data.get("verify")
    if not isinstance(verify, dict) or not verify.get("script"):
        return False, (f"{norm}: status: {status} 只能由验证器背书，frontmatter 缺少 "
                       "verify.script（与 verify.args）。")
    cmd = [venv_python(root), verify["script"]] + verify.get("args", "").split()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=240, cwd=root)
    except subprocess.TimeoutExpired:
        return False, f"{norm}: 验证器超时(240s)：{' '.join(cmd)}"
    out = (proc.stdout or "") + "\n" + (proc.stderr or "")
    mm = re.search(r"VERDICT:\s*(PASS|REFUTED|ERROR)", out)
    if proc.returncode != 0 or not mm:
        return False, (f"{norm}: 验证器未正常给出 VERDICT（exit {proc.returncode}）。"
                       f"命令: {' '.join(cmd)}\n输出尾部:\n{out[-800:]}")
    got = mm.group(1)
    want = "PASS" if status == "numeric-verified" else "REFUTED"
    if got != want:
        return False, (f"{norm}: status: {status}，但验证器给出 VERDICT: {got}。"
                       "状态必须与验证结果一致——请依据 VERDICT 修正 status。")
    return True, ""
