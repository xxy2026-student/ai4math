"""Claude Code/OpenCode 状态门禁入口。

Claude Code 通过 stdin 传入 PostToolUse 事件；OpenCode 通过 ``--all`` 调用。
所有可能写文件的工具都执行一次全树检查，避免 Bash/apply_patch 绕过单文件
门禁。违规时 exit 2，并把原因写到 stderr。
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gate  # noqa: E402


MUTATING_TOOLS = {
    "write",
    "edit",
    "multiedit",
    "notebookedit",
    "applypatch",
    "apply_patch",
    "bash",
}


def project_root(explicit=None):
    """Return the repository root used by hooks in either runtime."""
    return os.path.abspath(
        explicit or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    )


def venv_interpreter(root):
    """Choose the repository venv on Windows or POSIX, then current Python."""
    candidates = (
        os.path.join(root, ".venv", "Scripts", "python.exe"),
        os.path.join(root, ".venv", "bin", "python"),
    )
    for candidate in candidates:
        if os.path.isfile(candidate):
            return candidate
    return sys.executable


def _fallback_check_tree(root):
    """Compatibility fallback while older gate.py lacks check_tree()."""
    failures = []
    skip = {".git", ".venv", "node_modules", "__pycache__"}
    problems = os.path.join(root, "problems")
    if not os.path.isdir(problems):
        return True, ""
    for current, dirs, files in os.walk(problems):
        dirs[:] = [name for name in dirs if name not in skip]
        if os.path.basename(current) not in {"conjectures", "lemmas"}:
            continue
        for name in sorted(files):
            if not name.lower().endswith(".md"):
                continue
            path = os.path.join(current, name)
            ok, msg = gate.check_file(path, root=root, execute_verifiers=False)
            if not ok:
                failures.append(msg)
    return (False, "\n".join(failures)) if failures else (True, "")


def check_tree(root):
    checker = getattr(gate, "check_tree", None)
    if checker is not None:
        return checker(root=root, execute_verifiers=False)
    return _fallback_check_tree(root)


def event_requires_check(event):
    name = str(event.get("tool_name") or event.get("tool") or "").lower()
    return name in MUTATING_TOOLS


def _maybe_reexec(root):
    """Run the hook itself in the project venv when one exists.

    The first launcher still needs a system ``python`` command, but all imports and
    verifier subprocesses after startup use the repository environment.
    """
    target = venv_interpreter(root)
    try:
        same = os.path.samefile(target, sys.executable)
    except (FileNotFoundError, OSError):
        same = os.path.normcase(os.path.abspath(target)) == os.path.normcase(
            os.path.abspath(sys.executable)
        )
    if not same and os.environ.get("AI4MATH_HOOK_REEXEC") != "1":
        env = os.environ.copy()
        env["AI4MATH_HOOK_REEXEC"] = "1"
        os.execve(target, [target, os.path.abspath(__file__), *sys.argv[1:]], env)


def _reject(msg):
    sys.stderr.write("[hook_gate] " + (msg or "状态门禁拒绝") + "\n")
    return 2


def main(argv=None):
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", default=None)
    args, _ = ap.parse_known_args(argv)
    root = project_root(args.root)
    _maybe_reexec(root)

    if args.all:
        ok, msg = check_tree(root)
        return 0 if ok else _reject(msg)

    try:
        event = json.loads(
            sys.stdin.buffer.read().decode("utf-8-sig", "replace") or "{}"
        )
    except json.JSONDecodeError:
        return 0
    if not event_requires_check(event):
        return 0
    ok, msg = check_tree(root)
    return 0 if ok else _reject(msg)


if __name__ == "__main__":
    sys.exit(main())
