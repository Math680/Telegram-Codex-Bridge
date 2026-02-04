#!/usr/bin/env python3
import json
import os
import subprocess
import sys


def parse_bool(value: str, default: bool = False) -> bool:
    if value is None:
        return default
    v = value.strip().lower()
    if v in {"1", "true", "yes", "on"}:
        return True
    if v in {"0", "false", "no", "off"}:
        return False
    return default


def main():
    codex_bin = os.environ.get("CODEX_BIN", "")
    if not codex_bin:
        sys.stderr.write("CODEX_BIN not set\n")
        return 127
    if not os.path.isfile(codex_bin) or not os.access(codex_bin, os.X_OK):
        sys.stderr.write(f"CODEX_BIN is not executable: {codex_bin}\n")
        return 126

    prompt = sys.stdin.read()

    session_id = os.environ.get("CODEX_SESSION_ID", "").strip()
    session_file = os.environ.get("CODEX_SESSION_FILE", "").strip()

    extra_args_common = []
    model = os.environ.get("CODEX_MODEL", "").strip()
    if model:
        extra_args_common += ["-m", model]

    reasoning = os.environ.get("CODEX_REASONING", "").strip()
    if reasoning:
        extra_args_common += ["-c", f"reasoning.level=\"{reasoning}\""]

    bypass = parse_bool(os.environ.get("CODEX_BYPASS_APPROVALS", "0"), False)
    skip_git = parse_bool(os.environ.get("CODEX_SKIP_GIT_CHECK", "1"), True)

    if session_id:
        # Note: exec resume supports a limited flag set. We avoid -C/--add-dir here.
        cmd = [codex_bin, "exec", "resume"]
        if skip_git:
            cmd += ["--skip-git-repo-check"]
        if bypass:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        cmd += ["--json", session_id, "-"]
        cmd += extra_args_common
    else:
        sandbox = os.environ.get("CODEX_SANDBOX", "workspace-write").strip()
        if sandbox not in {"read-only", "workspace-write", "danger-full-access"}:
            sandbox = "workspace-write"

        cmd = [codex_bin, "exec"]
        if skip_git:
            cmd += ["--skip-git-repo-check"]
        if bypass:
            cmd += ["--dangerously-bypass-approvals-and-sandbox"]
        else:
            cmd += ["--sandbox", sandbox]
        cmd += ["--json"]

        cwd = os.environ.get("CODEX_CWD", "").strip()
        if cwd:
            cmd += ["-C", cwd, "--add-dir", cwd]

        cmd += extra_args_common + ["-"]

    proc = subprocess.run(
        cmd,
        input=prompt,
        text=True,
        capture_output=True,
        shell=False,
    )

    thread_id = None
    last_text = None
    raw_stdout = proc.stdout or ""
    if raw_stdout:
        for line in raw_stdout.splitlines():
            try:
                evt = json.loads(line)
            except json.JSONDecodeError:
                continue
            if evt.get("type") == "thread.started" and evt.get("thread_id"):
                thread_id = evt["thread_id"]
            if evt.get("type") == "item.completed":
                item = evt.get("item", {})
                if item.get("type") == "agent_message" and item.get("text"):
                    last_text = item["text"]

    if not session_id and session_file and thread_id:
        try:
            with open(session_file, "w") as f:
                f.write(thread_id)
        except OSError:
            pass

    if proc.returncode != 0 and proc.stderr:
        sys.stderr.write(proc.stderr)

    if last_text:
        sys.stdout.write(last_text)
    elif raw_stdout:
        sys.stdout.write(raw_stdout)

    return proc.returncode


if __name__ == "__main__":
    sys.exit(main())
