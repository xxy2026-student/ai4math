"""远程实验执行器（ssh 直连 + nohup）。

用法（仓库根目录，.venv 的 python 运行）：

    python remote/remote_run.py check --host a100                # 连通性与环境探测
    python remote/remote_run.py push  --host a100 --problem <p>  # 同步验证器与实验脚本
    python remote/remote_run.py setup --host a100                # 远端建 .venv 装依赖
    python remote/remote_run.py run   --host a100 --cmd "{python} problems/<p>/experiments/sweep.py"
    python remote/remote_run.py status [--job <id>]              # 查任务状态 + 日志尾部
    python remote/remote_run.py log   --job <id> [-n 50]         # 看日志
    python remote/remote_run.py fetch --host a100 --problem <p>  # 拉回 results（只拉摘要与 evidence）

- 配置在 remote/hosts.yaml（模板 hosts.example.yaml；不入库）；
- 认证完全走系统 OpenSSH（~/.ssh 的 key 与 config），本脚本不读取、不复制、
  不上传任何密钥文件；BatchMode 运行，不支持密码交互；
- 纪律（CLAUDE.md）：向服务器提交任务前必须经用户确认。
"""
import argparse
import json
import os
import posixpath
import re
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOSTS_PATH = os.path.join(ROOT, "remote", "hosts.yaml")
JOBS_PATH = os.path.join(ROOT, "remote", "jobs.json")
SSH_OPTS = ["-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def load_host(alias):
    if not os.path.exists(HOSTS_PATH):
        die("缺少 remote/hosts.yaml——复制 remote/hosts.example.yaml 并填写（该文件不入库）。")
    with open(HOSTS_PATH, encoding="utf-8") as f:
        hosts = (yaml.safe_load(f) or {}).get("hosts") or {}
    if alias not in hosts:
        die(f"hosts.yaml 中没有主机 {alias!r}，现有：{', '.join(hosts) or '(空)'}")
    h = dict(hosts[alias])
    h.setdefault("python", "python3")
    h.setdefault("workdir", "~/ai4math-exp")
    return h


def ssh_run(h, cmd, timeout=60):
    return subprocess.run(["ssh", *SSH_OPTS, h["ssh"], cmd],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def scp_run(args_, timeout=600):
    return subprocess.run(["scp", *SSH_OPTS, "-r", *args_],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)


def load_jobs():
    if os.path.exists(JOBS_PATH):
        with open(JOBS_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_jobs(jobs):
    with open(JOBS_PATH, "w", encoding="utf-8") as f:
        json.dump(jobs, f, ensure_ascii=False, indent=2)


def cmd_check(a):
    h = load_host(a.host)
    probe = (f"echo CONN_OK && uname -sm && echo CPU=$(nproc) && "
             f"free -h | sed -n 2p && {h['python']} --version 2>&1 && "
             f"(ls {h['workdir']}/.venv/bin/python >/dev/null 2>&1 "
             f"&& echo VENV_READY || echo VENV_MISSING)")
    try:
        r = ssh_run(h, probe, timeout=60)
    except subprocess.TimeoutExpired:
        die(f"连接 {h['ssh']} 超时——检查网络/跳板是否可达。")
    print((r.stdout or "").strip())
    if "CONN_OK" not in r.stdout:
        die("连接失败：\n" + (r.stderr or "").strip())


def cmd_push(a):
    h = load_host(a.host)
    paths = ["verifiers", "requirements.txt"]
    for sub in ("experiments", "specs", "predicates"):
        p = f"problems/{a.problem}/{sub}"
        if os.path.isdir(os.path.join(ROOT, p)):
            paths.append(p)
    mkdirs = {posixpath.join(h["workdir"], posixpath.dirname(p)).rstrip("/")
              for p in paths}
    mkdirs.add(posixpath.join(h["workdir"], f"problems/{a.problem}/results"))
    r = ssh_run(h, "mkdir -p " + " ".join(sorted(d or h["workdir"] for d in mkdirs)))
    if r.returncode:
        die("远端建目录失败：\n" + r.stderr)
    for p in paths:
        dest = f"{h['ssh']}:{posixpath.join(h['workdir'], posixpath.dirname(p))}/"
        r = scp_run([os.path.join(ROOT, p), dest])
        print(("OK   " if r.returncode == 0 else "FAIL ") + p)
        if r.returncode:
            die(r.stderr.strip())


def cmd_setup(a):
    h = load_host(a.host)
    r = ssh_run(h, f"cd {h['workdir']} && {h['python']} -m venv .venv && "
                   ".venv/bin/pip install -q -r requirements.txt && echo SETUP_OK",
                timeout=1800)
    print((r.stdout or "").strip())
    if "SETUP_OK" not in r.stdout:
        die("远端环境安装失败：\n" + (r.stderr or "")[-1000:])


def cmd_run(a):
    h = load_host(a.host)
    job = time.strftime("%Y%m%d-%H%M%S")
    cmd = a.cmd.replace("{python}", ".venv/bin/python")
    log = f"logs/{job}.log"
    r = ssh_run(h, f"cd {h['workdir']} && mkdir -p logs && "
                   f"nohup {cmd} > {log} 2>&1 & echo PID=$!")
    m = re.search(r"PID=(\d+)", r.stdout or "")
    if not m:
        die("提交失败：\n" + (r.stdout or "") + (r.stderr or ""))
    jobs = load_jobs()
    jobs[job] = {"host": a.host, "pid": int(m.group(1)), "cmd": cmd,
                 "log": posixpath.join(h["workdir"], log),
                 "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    save_jobs(jobs)
    print(f"已提交 job {job}（pid {m.group(1)}），远端日志 {log}")


def _job(a):
    jobs = load_jobs()
    if not jobs:
        die("还没有提交过任务。")
    jid = a.job or sorted(jobs)[-1]
    if jid not in jobs:
        die(f"没有 job {jid}，现有：{', '.join(sorted(jobs))}")
    return jid, jobs[jid]


def cmd_status(a):
    jobs = load_jobs()
    if not jobs:
        die("还没有提交过任务。")
    sel = {a.job: jobs[a.job]} if a.job else jobs
    for jid, j in sorted(sel.items()):
        h = load_host(j["host"])
        r = ssh_run(h, f"(kill -0 {j['pid']} 2>/dev/null && echo STATE=RUNNING "
                       f"|| echo STATE=FINISHED); tail -n 3 {j['log']} 2>/dev/null")
        state = "RUNNING" if "STATE=RUNNING" in (r.stdout or "") else "FINISHED"
        print(f"[{jid}] {state}  host={j['host']}  始于 {j['started']}")
        tail = re.sub(r"STATE=\w+\n?", "", r.stdout or "").strip()
        if tail:
            print("    " + "\n    ".join(tail.splitlines()[-3:]))


def cmd_log(a):
    jid, j = _job(a)
    h = load_host(j["host"])
    r = ssh_run(h, f"tail -n {a.n} {j['log']}")
    print((r.stdout or r.stderr).strip())


def cmd_fetch(a):
    h = load_host(a.host)
    remote = posixpath.join(h["workdir"], f"problems/{a.problem}/results")
    local = os.path.join(ROOT, "problems", a.problem, "results")
    os.makedirs(local, exist_ok=True)
    r = scp_run([f"{h['ssh']}:{remote}/*", local])
    if r.returncode:
        die("拉取失败（远端可能还没有结果文件）：\n" + r.stderr.strip())
    print(f"已拉回 {remote}/* -> {os.path.relpath(local, ROOT)}")


def main():
    ap = argparse.ArgumentParser(description="ai4math 远程实验执行器（ssh 直连）")
    sub = ap.add_subparsers(dest="op", required=True)
    for name, fn, args_ in [
        ("check", cmd_check, ["host"]),
        ("push", cmd_push, ["host", "problem"]),
        ("setup", cmd_setup, ["host"]),
        ("run", cmd_run, ["host", "cmd"]),
        ("status", cmd_status, ["job?"]),
        ("log", cmd_log, ["job?", "n"]),
        ("fetch", cmd_fetch, ["host", "problem"]),
    ]:
        p = sub.add_parser(name)
        if "host" in args_:
            p.add_argument("--host", required=True)
        if "problem" in args_:
            p.add_argument("--problem", required=True)
        if "cmd" in args_:
            p.add_argument("--cmd", required=True,
                           help="远端命令；python 写 {python} 占位符（替换为远端 .venv）")
        if "job?" in args_:
            p.add_argument("--job", default=None)
        if "n" in args_:
            p.add_argument("-n", type=int, default=50)
        p.set_defaults(fn=fn)
    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
