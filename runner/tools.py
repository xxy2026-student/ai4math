"""通用 runner 的本地工具箱：文件、shell、网络检索。

- 文件操作限制在仓库根目录内；
- write_file 之后自动过状态门禁（verifiers/gate.py），拒绝理由作为工具结果
  返还给模型（文件保留，模型须修正后重写——与 Claude Code hook 行为一致）；
- 检索默认只依赖免 key 的 arXiv / Semantic Scholar API 与通用 fetch_url，
  保证任何模型任何环境都可用。
"""
import html
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verifiers"))
from gate import check_file, venv_python  # noqa: E402

UA = {"User-Agent": "ai4math-runner/0.1"}


def _abs(path):
    p = os.path.abspath(os.path.join(ROOT, str(path)))
    try:
        ok = os.path.commonpath([os.path.normcase(ROOT), os.path.normcase(p)]) \
            == os.path.normcase(ROOT)
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"路径越出仓库范围: {path}")
    return p


def read_file(path, max_chars=20000):
    with open(_abs(path), encoding="utf-8-sig") as f:
        text = f.read()
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...[截断，全文共 {len(text)} 字符]"
    return text


def write_file(path, content):
    p = _abs(path)
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    ok, msg = check_file(str(path), root=ROOT)
    if not ok:
        return (f"[状态门禁拒绝] {msg}\n"
                "（文件已写入但不合规，请修正 status/verify/audit 后重写。）")
    return f"已写入 {path}（{len(content)} 字符）"


def list_dir(path="."):
    rows = []
    for name in sorted(os.listdir(_abs(path))):
        if name in (".git", ".venv", "__pycache__"):
            continue
        full = os.path.join(_abs(path), name)
        rows.append(name + "/" if os.path.isdir(full)
                    else f"{name} ({os.path.getsize(full)}B)")
    return "\n".join(rows) or "(空目录)"


def run(command, timeout=300):
    command = str(command).replace("{python}", venv_python(ROOT))
    try:
        proc = subprocess.run(command, shell=True, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=int(timeout))
    except subprocess.TimeoutExpired:
        return f"[超时 {timeout}s] {command}"
    out = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    return f"[exit {proc.returncode}]\n{out}"


def _get(url, timeout=60):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")


def fetch_url(url, max_chars=20000):
    try:
        text, ctype = _get(url)
    except (urllib.error.URLError, OSError) as e:
        return f"[抓取失败] {url}: {e}"
    if "html" in ctype:
        text = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(re.sub(r"[ \t]+", " ", text))
        text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text[:max_chars] + ("\n...[截断]" if len(text) > max_chars else "")


def search_arxiv(query, max_results=10):
    url = "https://export.arxiv.org/api/query?" + urllib.parse.urlencode(
        {"search_query": query, "max_results": int(max_results),
         "sortBy": "relevance"})
    try:
        text, _ = _get(url)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        out = []
        for e in ET.fromstring(text).findall("a:entry", ns):
            title = re.sub(r"\s+", " ", e.findtext("a:title", "", ns)).strip()
            link = e.findtext("a:id", "", ns)
            date = e.findtext("a:published", "", ns)[:10]
            summ = re.sub(r"\s+", " ", e.findtext("a:summary", "", ns)).strip()[:300]
            out.append(f"- {title} ({date})\n  {link}\n  {summ}")
        return "\n".join(out) or "(无结果)"
    except Exception as e:
        return f"[arXiv 检索失败] {type(e).__name__}: {e}"


def search_semantic_scholar(query, limit=10):
    url = "https://api.semanticscholar.org/graph/v1/paper/search?" + \
        urllib.parse.urlencode({"query": query, "limit": int(limit),
                                "fields": "title,year,authors,url,abstract,externalIds"})
    try:
        text, _ = _get(url)
        out = []
        for p in json.loads(text).get("data", []):
            auth = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            line = f"- {p.get('title')} ({p.get('year')}) — {auth}\n  {p.get('url')}"
            arx = (p.get("externalIds") or {}).get("ArXiv")
            if arx:
                line += f"  [arXiv:{arx}]"
            ab = (p.get("abstract") or "")[:200]
            if ab:
                line += f"\n  {ab}"
            out.append(line)
        return "\n".join(out) or "(无结果)"
    except Exception as e:
        return f"[Semantic Scholar 检索失败] {type(e).__name__}: {e}（该 API 偶有限流，稍后重试）"


_IMPL = {"read_file": read_file, "write_file": write_file, "list_dir": list_dir,
         "run": run, "fetch_url": fetch_url, "search_arxiv": search_arxiv,
         "search_semantic_scholar": search_semantic_scholar}


def dispatch(name, args):
    fn = _IMPL.get(name)
    if fn is None:
        return f"[未知工具] {name}"
    try:
        return fn(**args)
    except TypeError as e:
        return f"[参数错误] {name}: {e}"
    except Exception as e:
        return f"[工具异常] {name}: {type(e).__name__}: {e}"


def _fn(name, desc, props, required):
    return {"type": "function",
            "function": {"name": name, "description": desc,
                         "parameters": {"type": "object", "properties": props,
                                        "required": required}}}


_S = {"type": "string"}
_I = {"type": "integer"}
SCHEMAS = [
    _fn("read_file", "读仓库内的文本文件",
        {"path": {**_S, "description": "相对仓库根的路径"}, "max_chars": _I}, ["path"]),
    _fn("write_file", "写仓库内文件（覆盖）。conjectures/lemmas 下的文件会自动过状态门禁，"
        "被拒时拒绝理由随结果返回，须修正后重写",
        {"path": _S, "content": _S}, ["path", "content"]),
    _fn("list_dir", "列出仓库内某目录的一层内容", {"path": _S}, []),
    _fn("run", "在仓库根目录执行 shell 命令。跑验证器/实验脚本时 python 解释器一律写 "
        "{python} 占位符（自动替换为 .venv 解释器）",
        {"command": _S, "timeout": {**_I, "description": "秒，默认 300"}}, ["command"]),
    _fn("fetch_url", "抓取网页正文（HTML 自动转纯文本），用于读 arXiv abs/ar5iv 全文等",
        {"url": _S, "max_chars": _I}, ["url"]),
    _fn("search_arxiv", "arXiv 论文检索（免 key）", {"query": _S, "max_results": _I}, ["query"]),
    _fn("search_semantic_scholar", "Semantic Scholar 论文检索（免 key）",
        {"query": _S, "limit": _I}, ["query"]),
]
