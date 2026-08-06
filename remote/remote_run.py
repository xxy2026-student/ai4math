"""远程实验执行器（ssh 直连 + nohup）。

典型流程（仓库根目录，使用 .venv 的 Python）：

    python remote/remote_run.py check --host a100
    python remote/remote_run.py push --host a100 --problem <p>
    python remote/remote_run.py setup --host a100
    python remote/remote_run.py authorize --host a100 --cmd "{python} ..."
    python remote/remote_run.py run --host a100 --cmd "{python} ..." --approval-token <token>
    python remote/remote_run.py status [--job <id>]
    python remote/remote_run.py fetch --host a100 --problem <p>

``authorize`` 必须在交互终端由用户确认，签发一个与 host、cmd 和当时解析出的
ssh/workdir/python 配置绑定、15 分钟过期且只可消费一次的 token。状态文件只保存
token 的 SHA-256 摘要，并用跨进程文件锁串行消费。它能防止正常 agent 工作流误提交，
但不是针对拥有本机状态文件写权限或 SSH 权限的恶意进程的安全边界。

``push`` 与 ``setup`` 也会改变远端状态，必须由交互终端逐次确认；无人值守
agent 不能替用户回答。

fetch 默认只取 results/ 顶层不超过 1 MiB 的 manifest/evidence/summary 文件；
原始数组和大型产物留在远端。
"""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
import posixpath
import re
import secrets
import shlex
import subprocess
import sys
import time

try:
    import yaml
except ModuleNotFoundError:  # 允许状态/授权逻辑在最小 Python 环境中被导入和测试。
    yaml = None

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS_PATH = os.path.join(ROOT, "remote", "hosts.yaml")
JOBS_PATH = os.path.join(ROOT, "remote", "jobs.json")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
STATE_VERSION = 3
APPROVAL_TTL_SECONDS = 15 * 60
DEFAULT_FETCH_MAX_BYTES = 1024 * 1024
STATE_LOCK_PATH = JOBS_PATH + ".lock"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_SSH_TARGET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@:-]*$")
SAFE_REMOTE_TOKEN = re.compile(r"^(?:~|/)?[A-Za-z0-9_./+-]+$")


def die(msg):
    print(msg, file=sys.stderr)
    raise SystemExit(1)


def validate_problem(name):
    if not SAFE_NAME.fullmatch(str(name or "")):
        die("problem 名只能包含字母、数字、点、下划线和连字符。")
    return name


def quote_remote(value):
    """Quote one trusted remote path/command token while preserving ``~/``."""
    value = str(value)
    if not SAFE_REMOTE_TOKEN.fullmatch(value):
        die(f"远端路径/命令 token 含不支持的字符: {value!r}")
    if value == "~":
        return '"$HOME"'
    if value.startswith("~/"):
        return '"$HOME"/' + shlex.quote(value[2:])
    return shlex.quote(value)


def load_host(alias):
    if yaml is None:
        die("读取 remote/hosts.yaml 需要 PyYAML；请先安装 requirements.txt。")
    if not os.path.exists(HOSTS_PATH):
        die("缺少 remote/hosts.yaml——复制 remote/hosts.example.yaml 并填写（该文件不入库）。")
    with open(HOSTS_PATH, encoding="utf-8") as f:
        hosts = (yaml.safe_load(f) or {}).get("hosts") or {}
    if alias not in hosts:
        die(f"hosts.yaml 中没有主机 {alias!r}，现有：{', '.join(hosts) or '(空)'}")
    if not isinstance(hosts[alias], dict) or not hosts[alias].get("ssh"):
        die(f"hosts.yaml 的 {alias!r} 缺少 ssh 字段。")
    h = dict(hosts[alias])
    h.setdefault("python", "python3")
    h.setdefault("workdir", "~/ai4research-exp")
    if not SAFE_SSH_TARGET.fullmatch(str(h["ssh"])):
        die(f"hosts.yaml 的 {alias!r}.ssh 含不支持的字符。")
    # Validate these before they are interpolated into a remote shell command.
    quote_remote(h["workdir"])
    quote_remote(h["python"])
    return h


def ssh_run(h, cmd, timeout=60):
    return subprocess.run(
        ["ssh", *SSH_OPTS, h["ssh"], cmd],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def scp_run(args_, timeout=600):
    return subprocess.run(
        ["scp", *SSH_OPTS, "-r", *args_],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def _empty_state():
    return {"version": STATE_VERSION, "jobs": {}, "approvals": {}}


def load_state():
    if not os.path.exists(JOBS_PATH):
        return _empty_state()
    try:
        with open(JOBS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        die(f"无法读取 {os.path.relpath(JOBS_PATH, ROOT)}: {exc}")
    if not isinstance(raw, dict):
        die("remote/jobs.json 格式无效：顶层必须是对象。")
    if isinstance(raw.get("jobs"), dict):
        return {
            "version": STATE_VERSION,
            "jobs": raw["jobs"],
            "approvals": raw.get("approvals")
            if isinstance(raw.get("approvals"), dict)
            else {},
        }
    # v1 向后兼容：旧文件顶层就是 {job_id: job}。
    return {"version": STATE_VERSION, "jobs": raw, "approvals": {}}


def save_state(state):
    os.makedirs(os.path.dirname(JOBS_PATH), exist_ok=True)
    tmp = JOBS_PATH + f".tmp-{os.getpid()}-{secrets.token_hex(3)}"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, JOBS_PATH)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@contextmanager
def state_lock(timeout=10.0):
    """Serialize cross-process state updates; never allow double token consumption."""
    deadline = time.monotonic() + float(timeout)
    fd = None
    while fd is None:
        try:
            fd = os.open(STATE_LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()}\n".encode("ascii"))
        except FileExistsError:
            if time.monotonic() >= deadline:
                die(
                    "remote state lock 超时；可能有另一个进程正在更新状态。"
                    f"确认无进程后再处理 {STATE_LOCK_PATH}"
                )
            time.sleep(0.05)
    try:
        yield
    finally:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(STATE_LOCK_PATH)
        except FileNotFoundError:
            pass


def load_jobs():
    return load_state()["jobs"]


def save_jobs(jobs):
    with state_lock():
        state = load_state()
        state["jobs"] = jobs
        save_state(state)


def _approval_digest(host, command, host_config=None):
    host_config = host_config or {}
    payload = json.dumps(
        {
            "host": host,
            "command": command,
            "ssh": host_config.get("ssh"),
            "workdir": host_config.get("workdir"),
            "python": host_config.get("python"),
        },
        ensure_ascii=False,
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _token_key(token):
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()


def _prune_approvals(state, now=None):
    now = time.time() if now is None else now
    approvals = state.setdefault("approvals", {})
    for token in list(approvals):
        entry = approvals[token]
        if not isinstance(entry, dict) or float(entry.get("expires", 0)) <= now:
            approvals.pop(token, None)


def create_approval(host, command, host_config=None, now=None):
    now = time.time() if now is None else now
    token = secrets.token_urlsafe(18)
    with state_lock():
        state = load_state()
        _prune_approvals(state, now)
        state["approvals"][_token_key(token)] = {
            "digest": _approval_digest(host, command, host_config),
            "host": host,
            "created": now,
            "expires": now + APPROVAL_TTL_SECONDS,
        }
        save_state(state)
    return token


def consume_approval(token, host, command, host_config=None, now=None):
    now = time.time() if now is None else now
    with state_lock():
        state = load_state()
        _prune_approvals(state, now)
        approval = state["approvals"].pop(_token_key(token), None)
        # Consume before checking: a mismatched token cannot be retried against commands.
        save_state(state)
    if approval is None:
        die("缺少、已过期或已使用的 approval token；请由用户重新运行 authorize。")
    expected = _approval_digest(host, command, host_config)
    if not secrets.compare_digest(str(approval.get("digest", "")), expected):
        die("approval token 与本次 host/cmd 不匹配，且已作废。")


def cmd_authorize(a):
    h = load_host(a.host)  # Validate and bind the resolved target without contacting it.
    if not sys.stdin.isatty():
        die("authorize 只允许在交互终端运行，不能从无人值守 agent/shell 管道签发。")
    print("即将授权一次远程提交：")
    print(f"  host: {a.host}")
    print(f"  cmd:  {a.cmd}")
    answer = input(f"请输入 APPROVE {a.host} 继续：").strip()
    if answer != f"APPROVE {a.host}":
        die("未授权，未生成 token。")
    token = create_approval(a.host, a.cmd, h)
    print("一次性 approval token（15 分钟内有效，成功或失败尝试一次即作废）：")
    print(token)


def require_interactive_confirmation(action, host, detail=""):
    if not sys.stdin.isatty():
        die(f"{action} 会改变远端状态，只允许在交互终端由用户确认。")
    print(f"即将执行远端动作：{action}  host={host}")
    if detail:
        print(f"  scope: {detail}")
    expected = f"APPROVE {action} {host}"
    if input(f"请输入 {expected} 继续：").strip() != expected:
        die("未授权，远端未发生变化。")


def cmd_check(a):
    h = load_host(a.host)
    workdir = quote_remote(h["workdir"])
    python = quote_remote(h["python"])
    probe = (
        "echo CONN_OK && uname -sm && echo CPU=$(nproc) && "
        f"free -h | sed -n 2p && {python} --version 2>&1 && "
        f"(ls {workdir}/.venv/bin/python >/dev/null 2>&1 "
        "&& echo VENV_READY || echo VENV_MISSING)"
    )
    try:
        result = ssh_run(h, probe, timeout=60)
    except subprocess.TimeoutExpired:
        die(f"连接 {h['ssh']} 超时——检查网络/跳板是否可达。")
    print((result.stdout or "").strip())
    if result.returncode or "CONN_OK" not in (result.stdout or ""):
        die("连接失败：\n" + (result.stderr or "").strip())


def cmd_push(a):
    problem = validate_problem(a.problem)
    h = load_host(a.host)
    require_interactive_confirmation("push", a.host, f"problem={problem}")
    paths = ["verifiers", "requirements.txt"]
    for subdir in ("experiments", "specs", "predicates"):
        rel = f"problems/{problem}/{subdir}"
        if os.path.isdir(os.path.join(ROOT, rel)):
            paths.append(rel)
    mkdirs = {
        posixpath.join(h["workdir"], posixpath.dirname(rel)).rstrip("/")
        for rel in paths
    }
    mkdirs.add(posixpath.join(h["workdir"], f"problems/{problem}/results"))
    command = "mkdir -p " + " ".join(
        quote_remote(path or h["workdir"]) for path in sorted(mkdirs)
    )
    result = ssh_run(h, command)
    if result.returncode:
        die("远端建目录失败：\n" + (result.stderr or ""))
    for rel in paths:
        destination = (
            f"{h['ssh']}:"
            f"{posixpath.join(h['workdir'], posixpath.dirname(rel))}/"
        )
        result = scp_run([os.path.join(ROOT, rel), destination])
        print(("OK   " if result.returncode == 0 else "FAIL ") + rel)
        if result.returncode:
            die((result.stderr or "").strip())


def cmd_setup(a):
    h = load_host(a.host)
    require_interactive_confirmation("setup", a.host, h["workdir"])
    workdir = quote_remote(h["workdir"])
    python = quote_remote(h["python"])
    result = ssh_run(
        h,
        f"cd {workdir} && {python} -m venv .venv && "
        ".venv/bin/pip install -q -r requirements.txt && echo SETUP_OK",
        timeout=1800,
    )
    print((result.stdout or "").strip())
    if result.returncode or "SETUP_OK" not in (result.stdout or ""):
        die("远端环境安装失败：\n" + (result.stderr or "")[-1000:])


def _new_job_id():
    return time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(4)


def cmd_run(a):
    h = load_host(a.host)
    consume_approval(a.approval_token, a.host, a.cmd, h)
    job_id = _new_job_id()
    command = a.cmd.replace("{python}", ".venv/bin/python")
    log_rel = f"logs/{job_id}.log"
    exit_rel = f"logs/{job_id}.exit"
    wrapped = (
        f"sh -c {shlex.quote(command)}; rc=$?; "
        f"printf '%s\\n' \"$rc\" > {shlex.quote(exit_rel)}; "
        "exit \"$rc\""
    )
    remote_command = (
        f"cd {quote_remote(h['workdir'])} && mkdir -p logs && "
        f"(nohup sh -c {shlex.quote(wrapped)} > {shlex.quote(log_rel)} "
        "2>&1 < /dev/null & echo PID=$!)"
    )
    try:
        result = ssh_run(h, remote_command)
    except subprocess.TimeoutExpired:
        die("提交命令超时；approval token 已消费，请先检查远端再决定是否重新授权。")
    match = re.search(r"PID=(\d+)", result.stdout or "")
    if result.returncode or not match:
        die(
            "提交失败（approval token 已消费）：\n"
            + (result.stdout or "")
            + (result.stderr or "")
        )
    jobs = load_jobs()
    jobs[job_id] = {
        "host": a.host,
        "pid": int(match.group(1)),
        "cmd": command,
        "log": posixpath.join(h["workdir"], log_rel),
        "exit_file": posixpath.join(h["workdir"], exit_rel),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "state": "RUNNING",
        "exit_code": None,
    }
    save_jobs(jobs)
    print(f"已提交 job {job_id}（pid {match.group(1)}），远端日志 {log_rel}")


def _job(a):
    jobs = load_jobs()
    if not jobs:
        die("还没有提交过任务。")
    job_id = a.job or sorted(jobs)[-1]
    if job_id not in jobs:
        die(f"没有 job {job_id}，现有：{', '.join(sorted(jobs))}")
    return job_id, jobs[job_id]


def classify_status(result):
    if result.returncode:
        return "SSH_ERROR", None
    lines = (result.stdout or "").splitlines()
    state = next(
        (line.partition("=")[2] for line in lines if line.startswith("AI4MATH_STATE=")),
        "",
    )
    if state == "RUNNING":
        return "RUNNING", None
    if state == "EXIT":
        match = next(
            (
                re.fullmatch(r"AI4MATH_EXIT_CODE=(-?\d+)", line)
                for line in lines
                if line.startswith("AI4MATH_EXIT_CODE=")
            ),
            None,
        )
        if not match:
            return "UNKNOWN", None
        code = int(match.group(1))
        return ("SUCCEEDED" if code == 0 else "FAILED"), code
    return "UNKNOWN", None


def _exit_path(job):
    if job.get("exit_file"):
        return job["exit_file"]
    log = str(job.get("log", ""))
    return log[:-4] + ".exit" if log.endswith(".log") else log + ".exit"


def cmd_status(a):
    jobs = load_jobs()
    if not jobs:
        die("还没有提交过任务。")
    if a.job and a.job not in jobs:
        die(f"没有 job {a.job}，现有：{', '.join(sorted(jobs))}")
    selected = {a.job: jobs[a.job]} if a.job else jobs
    for job_id, job in sorted(selected.items()):
        h = load_host(job["host"])
        exit_file = quote_remote(_exit_path(job))
        log = quote_remote(job["log"])
        probe = (
            f"if [ -f {exit_file} ]; then echo AI4MATH_STATE=EXIT; "
            f"printf 'AI4MATH_EXIT_CODE='; cat {exit_file}; "
            f"elif kill -0 {int(job['pid'])} 2>/dev/null; then "
            "echo AI4MATH_STATE=RUNNING; "
            "else echo AI4MATH_STATE=UNKNOWN; fi; "
            f"tail -n 3 {log} 2>/dev/null"
        )
        try:
            result = ssh_run(h, probe)
            state, exit_code = classify_status(result)
        except (subprocess.TimeoutExpired, OSError) as exc:
            result = None
            state, exit_code = "SSH_ERROR", None
            error = f"{type(exc).__name__}: {exc}"
        else:
            error = (result.stderr or "").strip() if result.returncode else ""
        job["state"] = state
        job["exit_code"] = exit_code
        job["last_checked"] = time.strftime("%Y-%m-%d %H:%M:%S")
        suffix = f" exit={exit_code}" if exit_code is not None else ""
        print(f"[{job_id}] {state}{suffix}  host={job['host']}  始于 {job['started']}")
        if error:
            print("    " + error[-500:])
        if result is not None:
            tail = "\n".join(
                line
                for line in (result.stdout or "").splitlines()
                if not line.startswith("AI4MATH_STATE=")
                and not line.startswith("AI4MATH_EXIT_CODE=")
            ).strip()
            if tail:
                print("    " + "\n    ".join(tail.splitlines()[-3:]))
    save_jobs(jobs)


def cmd_log(a):
    _, job = _job(a)
    h = load_host(job["host"])
    try:
        result = ssh_run(h, f"tail -n {a.n} {quote_remote(job['log'])}")
    except subprocess.TimeoutExpired:
        die("读取远端日志超时。")
    if result.returncode:
        die("读取远端日志失败：\n" + (result.stderr or "").strip())
    print((result.stdout or "").strip())


def fetchable_artifact(name):
    if not SAFE_NAME.fullmatch(name):
        return False
    lower = name.lower()
    if lower in {"manifest.json", "evidence.json", "summary.md"}:
        return True
    return lower.endswith(
        (
            "_evidence.json",
            "-evidence.json",
            ".evidence.json",
            "_evidence.md",
            "-evidence.md",
            ".evidence.md",
            "_summary.md",
            "-summary.md",
            ".summary.md",
        )
    )


def cmd_fetch(a):
    problem = validate_problem(a.problem)
    if a.max_bytes <= 0:
        die("--max-bytes 必须为正数。")
    h = load_host(a.host)
    remote_dir = posixpath.join(h["workdir"], f"problems/{problem}/results")
    list_command = (
        f"find {quote_remote(remote_dir)} -maxdepth 1 -type f "
        f"-size -{int(a.max_bytes) + 1}c -printf '%f\\n'"
    )
    try:
        listing = ssh_run(h, list_command)
    except subprocess.TimeoutExpired:
        die("列出远端 evidence 超时。")
    if listing.returncode:
        die("无法列出远端 results：\n" + (listing.stderr or "").strip())
    names = sorted(
        {
            line.strip()
            for line in (listing.stdout or "").splitlines()
            if fetchable_artifact(line.strip())
        }
    )
    if not names:
        print("没有符合默认策略的小型 manifest/evidence/summary 文件；未拉取原始数据。")
        return
    local_dir = os.path.join(ROOT, "problems", problem, "results")
    os.makedirs(local_dir, exist_ok=True)
    fetched = []
    for name in names:
        remote_file = posixpath.join(remote_dir, name)
        result = scp_run([f"{h['ssh']}:{remote_file}", local_dir])
        if result.returncode:
            die(f"拉取 {name} 失败：\n" + (result.stderr or "").strip())
        fetched.append(name)
    print(
        f"已拉回 {len(fetched)} 个小型证据文件 -> "
        f"{os.path.relpath(local_dir, ROOT)}: {', '.join(fetched)}"
    )


def main():
    ap = argparse.ArgumentParser(description="AI4Research 远程实验执行器（ssh 直连）")
    sub = ap.add_subparsers(dest="op", required=True)

    check = sub.add_parser("check")
    check.add_argument("--host", required=True)
    check.set_defaults(fn=cmd_check)

    push = sub.add_parser("push")
    push.add_argument("--host", required=True)
    push.add_argument("--problem", required=True)
    push.set_defaults(fn=cmd_push)

    setup = sub.add_parser("setup")
    setup.add_argument("--host", required=True)
    setup.set_defaults(fn=cmd_setup)

    authorize = sub.add_parser("authorize")
    authorize.add_argument("--host", required=True)
    authorize.add_argument("--cmd", required=True)
    authorize.set_defaults(fn=cmd_authorize)

    run = sub.add_parser("run")
    run.add_argument("--host", required=True)
    run.add_argument("--cmd", required=True)
    run.add_argument("--approval-token", required=True)
    run.set_defaults(fn=cmd_run)

    status = sub.add_parser("status")
    status.add_argument("--job", default=None)
    status.set_defaults(fn=cmd_status)

    log = sub.add_parser("log")
    log.add_argument("--job", default=None)
    log.add_argument("-n", type=int, default=50)
    log.set_defaults(fn=cmd_log)

    fetch = sub.add_parser("fetch")
    fetch.add_argument("--host", required=True)
    fetch.add_argument("--problem", required=True)
    fetch.add_argument("--max-bytes", type=int, default=DEFAULT_FETCH_MAX_BYTES)
    fetch.set_defaults(fn=cmd_fetch)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
