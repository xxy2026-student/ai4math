"""通用 runner 的本地工具箱：文件、受限 Python、网络检索与人类决策闸门。

- 文件操作限制在仓库根目录内；
- write_file 在落盘前通过状态门禁；控制面只读，可执行研究文件须绑定人类决策；
- request_human_decision 生成不可覆盖的开放式决策卡，并由 agent loop 立即暂停；
- 不暴露任意 shell；问题代码执行须绑定顺序相连的设计决策、精确输入哈希与时间预算；
- 检索默认只依赖免 key 的 arXiv / Semantic Scholar API 与通用 fetch_url，
  保证任何模型任何环境都可用。
"""
import html
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import decisions

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "verifiers"))
from gate import venv_python  # noqa: E402

UA = {"User-Agent": "ai4research-runner/0.2"}
CONTROL_DIRS = {
    ".claude", ".git", ".github", ".opencode", "adapters", "decisions",
    "remote", "runner", "tests", "verifiers",
}
CONTROL_FILES = {
    "AGENTS.md", "CLAUDE.md", "requirements.txt", "setup.bat", "setup.ps1",
    "setup.sh",
}
EXECUTABLE_SUFFIXES = {
    ".bat", ".cmd", ".ipynb", ".js", ".jl", ".m", ".mjs", ".ps1",
    ".py", ".r", ".sh",
}
SENSITIVE_READ_FILES = {
    ".claude/settings.local.json", "remote/hosts.yaml", "remote/jobs.json",
    "runner/config.yaml",
}


def _abs(path):
    root = os.path.realpath(ROOT)
    p = os.path.realpath(os.path.join(root, str(path)))
    try:
        ok = os.path.commonpath([os.path.normcase(root), os.path.normcase(p)]) \
            == os.path.normcase(root)
    except ValueError:
        ok = False
    if not ok:
        raise ValueError(f"路径越出仓库范围: {path}")
    return p


def read_file(path, max_chars=20000):
    absolute = _abs(path)
    rel = os.path.relpath(absolute, os.path.realpath(ROOT)).replace("\\", "/")
    if rel.startswith("decisions/") or os.path.normcase(rel) in {
        os.path.normcase(x) for x in SENSITIVE_READ_FILES
    }:
        raise ValueError(f"{rel} 是人类控制/私密状态，模型工具不得读取")
    with open(absolute, encoding="utf-8-sig") as f:
        text = f.read()
    if len(text) > max_chars:
        return text[:max_chars] + f"\n...[截断，全文共 {len(text)} 字符]"
    return text


def _assert_model_writable(path):
    root = os.path.realpath(ROOT)
    rel = os.path.relpath(path, root).replace("\\", "/")
    first = rel.split("/", 1)[0]
    if os.path.normcase(first) in {os.path.normcase(x) for x in CONTROL_DIRS}:
        raise ValueError(f"{first}/ 是研究框架控制目录，模型工具不得写入")
    if os.path.normcase(rel) in {os.path.normcase(x) for x in CONTROL_FILES}:
        raise ValueError(f"{rel} 是研究框架控制文件，模型工具不得写入")


def _atomic_write(path, content, binary=False):
    tmp = path + f".tmp-{os.getpid()}"
    try:
        mode = "xb" if binary else "x"
        kwargs = {} if binary else {"encoding": "utf-8", "newline": "\n"}
        with open(tmp, mode, **kwargs) as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _workflow_write_stages(rel):
    """Return the human gate stages required before writing this artifact."""
    parts = rel.split("/")
    if len(parts) >= 3 and parts[0] == "ideas" and parts[-1] != "idea.md":
        return {"problem"}
    if len(parts) >= 3 and parts[0] == "problems":
        if parts[2] == "model.md" or parts[2] in {
            "conjectures", "designs", "experiments", "lemmas", "predicates",
            "specs",
        }:
            return {"direction"}
        if parts[2] in {
            "audits", "counterexamples", "results",
        }:
            return {"design"}
    if parts and parts[0] == "paper":
        return {"claim"}
    return None


def write_file(path, content, decision_id=None):
    p = _abs(path)
    _assert_model_writable(p)
    rel = os.path.relpath(p, os.path.realpath(ROOT)).replace("\\", "/")
    from gate import check_text, check_tree, parse_frontmatter  # noqa: E402

    data = parse_frontmatter(str(content)) or {}
    parts = rel.split("/")
    managed_claim = (
        len(parts) >= 4 and parts[0] == "problems"
        and parts[2] in {"conjectures", "lemmas"} and rel.lower().endswith(".md")
    )
    disposition = data.get("human_disposition") if managed_claim else None
    declared_decision = data.get("decision") if managed_claim else None
    if declared_decision == "null":
        declared_decision = None

    scope_stages = _workflow_write_stages(rel)
    if managed_claim and disposition in {"accepted-with-scope", "revise", "reject"}:
        if not decision_id:
            raise ValueError("记录非 pending 的人类 claim 处置必须提供 decision_id")
        if declared_decision != decision_id:
            raise ValueError("claim frontmatter 的 decision 必须等于本次真实 decision_id")
        decisions.validate_claim_disposition(
            decision_id, disposition, root=ROOT, subject_path=rel
        )
        scope_stages = {"claim"} if disposition == "accepted-with-scope" else None

    if os.path.splitext(rel)[1].lower() in EXECUTABLE_SUFFIXES:
        scope_stages = scope_stages or {"direction", "design"}
    if scope_stages:
        if not decision_id:
            raise ValueError(
                f"写入 {rel} 必须提供已回复的 {sorted(scope_stages)} decision_id"
            )
        if managed_claim and disposition == "accepted-with-scope" \
                and declared_decision != decision_id:
            raise ValueError("accepted-with-scope claim 的 decision 必须等于本次 decision_id")
        decisions.require_decision(
            decision_id,
            stages=scope_stages,
            root=ROOT,
            action_path=rel,
        )
    if len(parts) >= 4 and parts[0] == "problems" and parts[2] == "audits" \
            and os.path.exists(p):
        raise ValueError("audit artifact 不可覆盖；请创建带新版本/编号的审计文件")
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    # 普通写入只做无代码执行的结构/哈希检查。验证器只能通过 run_python
    # 或显式 gate CLI 运行，不能被一次无关 Markdown/JSON 写入偷偷触发。
    ok, msg = check_text(str(path), str(content), root=ROOT, execute_verifiers=False)
    if not ok:
        return f"[状态门禁拒绝，文件未写入] {msg}"
    if scope_stages:
        decisions.authorize_action(
            decision_id,
            stages=scope_stages,
            root=ROOT,
            action_path=rel,
            action_fingerprint={
                "kind": "write_file",
                "path": rel,
                "content_sha256": hashlib.sha256(
                    str(content).encode("utf-8")
                ).hexdigest(),
            },
        )
    existed = os.path.exists(p)
    previous = None
    if existed:
        with open(p, "rb") as f:
            previous = f.read()
    _atomic_write(p, str(content))
    try:
        ok, msg = check_tree(root=ROOT, execute_verifiers=False)
    except Exception as exc:
        ok, msg = False, f"全树门禁异常：{type(exc).__name__}: {exc}"
    if not ok:
        # Dependency changes (spec/predicate/verifier) can invalidate another
        # claim. Restore the user's prior file, then rerun the tree to refresh
        # any evidence file the failed validation may have touched.
        if existed:
            _atomic_write(p, previous, binary=True)
        else:
            os.unlink(p)
        try:
            restored, restore_msg = check_tree(root=ROOT, execute_verifiers=False)
        except Exception as exc:
            restored = False
            restore_msg = f"{type(exc).__name__}: {exc}"
        suffix = "" if restored else f"；回滚后门禁仍失败：{restore_msg}"
        return f"[全树门禁拒绝，写入已回滚] {msg}{suffix}"
    return f"已写入 {path}（{len(content)} 字符）"


def request_human_decision(stage, question, recommendation, recommended_option,
                           options, resume_prompt, evidence=None,
                           uncertainties=None, allow_multiple=False,
                           parent_decision_id=None, decision_id=None,
                           why_now="", confidence="",
                           strongest_counterargument="",
                           change_conditions=None, approval_scope=None,
                           reask_triggers=None, context_paths=None,
                           authorized_paths=None, authorizing_option_ids=None,
                           max_runtime_seconds=0, max_uses=0):
    """创建决策卡。agent_loop 识别返回值后立即停止本轮，等待用户明确选择。"""
    item = decisions.create_request(
        stage=stage,
        question=question,
        recommendation=recommendation,
        recommended_option=recommended_option,
        options=options,
        resume_prompt=resume_prompt,
        evidence=evidence,
        uncertainties=uncertainties,
        allow_multiple=allow_multiple,
        parent_decision_id=parent_decision_id,
        decision_id=decision_id,
        root=ROOT,
        why_now=why_now,
        confidence=confidence,
        strongest_counterargument=strongest_counterargument,
        change_conditions=change_conditions,
        approval_scope=approval_scope,
        reask_triggers=reask_triggers,
        context_paths=context_paths,
        authorized_paths=authorized_paths,
        authorizing_option_ids=authorizing_option_ids,
        max_runtime_seconds=max_runtime_seconds,
        max_uses=max_uses,
    )
    return {
        "kind": "human_decision_required",
        "decision_id": item["request"]["decision_id"],
        "message": decisions.render_card(item),
    }


def is_human_decision(value):
    return isinstance(value, dict) and value.get("kind") == "human_decision_required"


def list_dir(path="."):
    rows = []
    for name in sorted(os.listdir(_abs(path))):
        if name in (".git", ".venv", "__pycache__"):
            continue
        full = os.path.join(_abs(path), name)
        rows.append(name + "/" if os.path.isdir(full)
                    else f"{name} ({os.path.getsize(full)}B)")
    return "\n".join(rows) or "(空目录)"


def _file_digest(rel):
    with open(_abs(rel), "rb") as handle:
        return "sha256:" + hashlib.sha256(handle.read()).hexdigest()


def _spec_execution_bundle(spec, require_predicate):
    """Resolve every problem-controlled input/output reachable from a spec."""
    spec_rel = os.path.relpath(_abs(spec), os.path.realpath(ROOT)).replace("\\", "/")
    parts = spec_rel.split("/")
    if (len(parts) < 4 or parts[0] != "problems" or parts[2] != "specs"
            or not spec_rel.lower().endswith(".json") or not os.path.isfile(_abs(spec_rel))):
        raise ValueError("--spec 必须是 problems/<name>/specs/ 下已有的 JSON 文件")
    try:
        with open(_abs(spec_rel), encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 spec JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("spec JSON 顶层必须是对象")

    problem = parts[1]
    action_paths = [spec_rel]
    context_inputs = [spec_rel]
    inputs = [{"path": spec_rel, "sha256": _file_digest(spec_rel)}]
    outputs = []

    predicate = data.get("predicate")
    if require_predicate and not predicate:
        raise ValueError("反例验证 spec 必须声明 predicate")
    if predicate:
        predicate_rel = os.path.relpath(
            _abs(predicate), os.path.realpath(ROOT)
        ).replace("\\", "/")
        expected = f"problems/{problem}/predicates/"
        if (not predicate_rel.startswith(expected)
                or not predicate_rel.lower().endswith(".py")
                or not os.path.isfile(_abs(predicate_rel))):
            raise ValueError(f"predicate 必须是 {expected} 下已有的 Python 文件")
        action_paths.append(predicate_rel)
        context_inputs.append(predicate_rel)
        inputs.append({"path": predicate_rel, "sha256": _file_digest(predicate_rel)})

    evidence = data.get("evidence")
    if require_predicate and not evidence:
        raise ValueError("反例验证 spec 必须声明 evidence 输出")
    if evidence:
        evidence_rel = os.path.relpath(
            _abs(evidence), os.path.realpath(ROOT)
        ).replace("\\", "/")
        expected = f"problems/{problem}/results/"
        if not evidence_rel.startswith(expected) or not evidence_rel.lower().endswith(".json"):
            raise ValueError(f"evidence 必须位于 {expected}")
        action_paths.append(evidence_rel)
        outputs.append(evidence_rel)

    return {
        "spec": spec_rel,
        "action_paths": sorted(set(action_paths)),
        "context_inputs": sorted(set(context_inputs)),
        "inputs": inputs,
        "outputs": outputs,
    }


def run_python(path, args=None, timeout=300, decision_id=None):
    """无 shell 地运行受信验证器，或运行经人类方向/设计门批准的问题实验。"""
    p = _abs(path)
    if not os.path.isfile(p) or not p.lower().endswith(".py"):
        raise ValueError(f"只允许运行仓库内已有的 Python 文件: {path}")
    rel = os.path.relpath(p, ROOT).replace("\\", "/")
    parts = rel.split("/")
    timeout = int(timeout)
    if timeout < 1 or timeout > 86400:
        raise ValueError("timeout 必须在 1–86400 秒之间")
    if args is None:
        args = []
    if not isinstance(args, list) or not all(isinstance(x, str) for x in args):
        raise ValueError("args 必须是字符串数组")

    action_paths = []
    required_context_paths = []
    action_manifest = None
    if rel == "verifiers/gate.py":
        if args == ["--all", "--structure-only"]:
            pass
        else:
            raise ValueError(
                "模型工具只允许运行 gate.py --all --structure-only；"
                "可执行证据请运行带完整输入绑定的固定问题验证器，完整 gate 留给用户/CI"
            )
    elif rel in {
        "verifiers/search/counterexample_search.py",
        "verifiers/numeric/nash_check.py",
    }:
        if not decision_id:
            raise ValueError("运行问题代码必须提供已获人类回复的 decision_id")
        if len(args) != 2 or args[0] != "--spec":
            raise ValueError("问题验证器只允许参数 --spec <仓库内 spec.json>")
        bundle = _spec_execution_bundle(
            args[1], require_predicate=(rel == "verifiers/search/counterexample_search.py")
        )
        args = ["--spec", bundle["spec"]]
        action_paths = sorted(set(bundle["action_paths"] + [rel]))
        required_context_paths = sorted(set(bundle["context_inputs"] + [rel]))
        action_manifest = {
            "kind": "problem_verifier",
            "driver": rel,
            "driver_sha256": _file_digest(rel),
            "args": args,
            "inputs": bundle["inputs"],
            "outputs": bundle["outputs"],
        }
    elif len(parts) >= 4 and parts[0] == "problems" and parts[2] == "experiments":
        action_paths = [rel]
        required_context_paths = [rel]
        action_manifest = {
            "kind": "experiment",
            "path": rel,
            "script_sha256": _file_digest(rel),
            "args": args,
        }
    else:
        raise ValueError("只能运行固定验证器或 problems/<name>/experiments/ 下的脚本")

    if action_paths:
        if not decision_id:
            raise ValueError("运行问题代码必须提供已获人类回复的 decision_id")
        decisions.authorize_action(
            decision_id,
            stages={"design"},
            root=ROOT,
            action_paths=action_paths,
            required_context_paths=required_context_paths,
            runtime_seconds=timeout,
            action_fingerprint=action_manifest,
        )
    argv = [venv_python(ROOT), p]
    argv.extend(args)
    try:
        proc = subprocess.run(argv, shell=False, cwd=ROOT, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"[超时 {timeout}s] {rel}"
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
         "run_python": run_python, "fetch_url": fetch_url, "search_arxiv": search_arxiv,
         "search_semantic_scholar": search_semantic_scholar,
         "request_human_decision": request_human_decision}


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
_B = {"type": "boolean"}
_A_S = {"type": "array", "items": _S}
_OPTIONS = {
    "type": "array",
    "minItems": 2,
    "maxItems": 4,
    "items": {
        "type": "object",
        "properties": {
            "id": _S,
            "label": _S,
            "description": _S,
            "tradeoffs": _A_S,
            "claim_disposition": {
                "type": "string",
                "enum": ["pending", "accepted-with-scope", "revise", "reject"],
                "description": "CLAIM_GATE 必填；该选项被选择时唯一对应的人类处置",
            },
        },
        "required": ["id", "label", "description"],
    },
}
SCHEMAS = [
    _fn("read_file", "读仓库内的文本文件",
        {"path": {**_S, "description": "相对仓库根的路径"}, "max_chars": _I}, ["path"]),
    _fn("write_file", "写研究产物并运行结构门禁；框架控制面不可写。问题脚本/spec/predicate"
        "的编写必须绑定顺序相连的 direction 决策，结果/审计等下游产物绑定 design。",
        {"path": _S, "content": _S, "decision_id": _S}, ["path", "content"]),
    _fn("list_dir", "列出仓库内某目录的一层内容", {"path": _S}, []),
    _fn("run_python", "不经过 shell 运行固定验证器或问题实验；执行必须绑定顺序相连的 "
        "design 决策，实验脚本或 verifier driver、spec、predicate 的精确哈希须已进入 "
        "context_paths，所有传递路径"
        "须在 authorized_paths 内。",
        {"path": _S, "args": _A_S,
         "timeout": {**_I, "description": "秒，必须不超过决策卡预算"},
         "decision_id": _S}, ["path"]),
    _fn("fetch_url", "抓取网页正文（HTML 自动转纯文本），用于读 arXiv abs/ar5iv 全文等",
        {"url": _S, "max_chars": _I}, ["url"]),
    _fn("search_arxiv", "arXiv 论文检索（免 key）", {"query": _S, "max_results": _I}, ["query"]),
    _fn("search_semantic_scholar", "Semantic Scholar 论文检索（免 key）",
        {"query": _S, "limit": _I}, ["query"]),
    _fn(
        "request_human_decision",
        "在会改变研究方向、问题定义、关键假设、实验资源、结论措辞或发布状态时，"
        "向用户提交开放式决策卡并暂停。必须给出 LLM 推荐、信心、依据、不确定性、"
        "最强反对意见、批准范围、重新询问条件和 2–4 个实质性选项；用户始终可自定义、"
        "组合或要求继续讨论。五门必须通过 parent_decision_id 顺序连接；CLAIM_GATE 选项"
        "必须声明 claim_disposition。没有默认批准；此工具必须单独调用。",
        {
            "stage": {"type": "string",
                      "enum": ["problem", "direction", "design", "claim", "release"],
                      "description": "五个人类门；条件门复用最接近的阶段"},
            "question": _S,
            "why_now": {**_S, "description": "为何当前节点必须由人类作价值或范围判断"},
            "recommendation": _S,
            "recommended_option": _S,
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "strongest_counterargument": _S,
            "change_conditions": _A_S,
            "options": _OPTIONS,
            "resume_prompt": {**_S, "description": "用户决定后新会话可独立理解的恢复说明"},
            "evidence": _A_S,
            "uncertainties": _A_S,
            "approval_scope": {**_A_S, "description": "本次批准后可继续执行的具体范围"},
            "reask_triggers": {**_A_S, "description": "何时必须重新暂停询问"},
            "context_paths": {**_A_S, "description": "作为决策依据、需绑定内容哈希的仓库文件"},
            "authorized_paths": {**_A_S, "description": "批准后允许创建/执行的仓库相对路径前缀；可指向尚未创建的目录"},
            "authorizing_option_ids": {**_A_S, "description": "只有选择这些已有 option id 才激活批准范围；custom 默认不授权"},
            "max_runtime_seconds": {**_I, "description": "批准的单次本地运行上限；0 表示不授权运行"},
            "max_uses": {**_I, "description": "该 envelope 最多可消费的受控动作次数；0 表示无机器动作"},
            "allow_multiple": _B,
            "parent_decision_id": _S,
            "decision_id": _S,
        },
        ["stage", "question", "why_now", "recommendation", "recommended_option",
         "confidence", "strongest_counterargument", "options", "resume_prompt",
         "approval_scope", "reask_triggers", "authorized_paths",
         "authorizing_option_ids",
         "max_runtime_seconds", "max_uses"],
    ),
]
