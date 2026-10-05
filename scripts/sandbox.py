#!/usr/bin/env python3
"""Create disposable sbx workspaces without mounting the host checkout."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parents[1]
ENVIRONMENT = ROOT / "sandbox/sbxenv.yaml"
WORKSPACE = "/home/agent/workspace"
SBX = shutil.which("sbx") or str(Path.home() / ".local/bin/sbx")


def run(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, check=True, **kwargs)


def output(*args):
    return run(*args, stdout=subprocess.PIPE).stdout


def environment_args(name, agent, template):
    return [str(ENVIRONMENT), "--env-arg", f"name={name}",
            "--env-arg", f"agent={agent}", "--env-arg", f"template={template}"]


def seed(name, agent, template):
    # Refuse to reset an existing guest checkout, including after a partial run.
    run(SBX, "exec", name, "test", "!", "-e", f"{WORKSPACE}/.git")
    base = output("git", "rev-parse", "HEAD").decode().strip()
    patch = output("git", "diff", "--binary", "--no-ext-diff", "HEAD")
    untracked = output("git", "ls-files", "--others", "--exclude-standard", "-z")
    with tempfile.TemporaryDirectory(prefix="swim-sandbox-") as temporary:
        bundle = Path(temporary) / "source.bundle"
        run("git", "bundle", "create", str(bundle), "HEAD")
        with bundle.open("rb") as stream:
            run(SBX, "exec", "-i", name, "sh", "-c",
                "cat > /tmp/swim-source.bundle", stdin=stream)
        run(SBX, "exec", "-w", WORKSPACE, name, "bash", "-ec",
            "git init -b main; git fetch /tmp/swim-source.bundle HEAD; "
            "git reset --hard FETCH_HEAD; rm /tmp/swim-source.bundle")
        if patch:
            run(SBX, "exec", "-i", "-w", WORKSPACE, name, "git", "apply",
                "--binary", "--whitespace=nowarn", "-", input=patch)
        archive = Path(temporary) / "untracked.tar"
        with tarfile.open(archive, "w") as tar:
            for raw_path in untracked.split(b"\0"):
                if raw_path:
                    path = raw_path.decode()
                    tar.add(ROOT / path, arcname=path, recursive=False)
        with archive.open("rb") as stream:
            run(SBX, "exec", "-i", name, "tar", "-xf", "-", "-C", WORKSPACE,
                stdin=stream)
    run(SBX, "exec", "-i", name, "sh", "-c",
        "cat > /home/agent/.swim-sandbox-base", input=(base + "\n").encode())
    state = ROOT / ".sandbox" / f"{name}.json"
    state.parent.mkdir(exist_ok=True)
    state.write_text(json.dumps({"name": name, "agent": agent,
                                 "template": template, "base": base}, indent=2) + "\n")
    run(SBX, "exec", "-w", WORKSPACE, name, "devenv", "shell", "--", "npm", "ci")
    run(SBX, "exec", "-w", WORKSPACE, name, "devenv", "shell", "--", "node",
        "node_modules/playwright-core/cli.js", "install", "--with-deps", "chromium", "webkit")
    run(SBX, "exec", "-w", WORKSPACE, name, "devenv", "shell", "--",
        "./node_modules/.bin/e2e-web", "install", "--with-deps", "chromium", "webkit")
    # Pin the project's Node for browser startup without concurrent devenv evaluation.
    run(SBX, "exec", "-w", WORKSPACE, name, "devenv", "shell", "--", "bash", "-ec", '''
        node_package=$(dirname "$(dirname "$(readlink -f "$(command -v node)")")")
        nix-store --add-root /home/agent/.local/lib/swim-sandbox/node-package \\
            --indirect --realise "$node_package"
    ''')
    run(SBX, "exec", name, "touch", "/home/agent/.swim-sandbox-ready")
    run(SBX, "exec", name, "python3", "-c", '''
import json, socket, time, urllib.request
for attempt in range(60):
    try:
        with urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=1) as response:
            assert json.load(response)["webSocketDebuggerUrl"]
        with socket.create_connection(("127.0.0.1", 5900), timeout=1) as connection:
            assert connection.recv(12).startswith(b"RFB ")
        break
    except (OSError, ValueError, AssertionError, KeyError):
        time.sleep(1)
else:
    raise SystemExit("Browser desktop did not start; inspect /tmp/swim-browser.log inside the sandbox")
''')
    print(f"Ready: just sandbox-attach {name}")
    run(SBX, "ports", name)


def export(name):
    run(SBX, "exec", "-w", WORKSPACE, name, "bash", "-ec", r'''
        export_dir=$(mktemp -d /tmp/swim-export.XXXXXX)
        export GIT_INDEX_FILE="$export_dir/index"
        git read-tree HEAD
        git add -A -- .
        git diff --cached --binary "$(cat /home/agent/.swim-sandbox-base)" \
            > "$export_dir/changes.patch"
        git bundle create "$export_dir/commits.bundle" HEAD
        cp /home/agent/.swim-sandbox-base "$export_dir/base.txt"
        rm "$GIT_INDEX_FILE"
        printf '%s' "$export_dir" > /tmp/swim-last-export
    ''')
    source = output(SBX, "exec", name, "cat", "/tmp/swim-last-export").decode().strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    destination = ROOT / ".sandbox/exports" / f"{name}-{stamp}"
    destination.mkdir(parents=True, exist_ok=False)
    for filename in ("changes.patch", "commits.bundle", "base.txt"):
        run(SBX, "cp", f"{name}:{source}/{filename}", str(destination / filename))
    print(f"Exported changes and commits to {destination}")
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "seed", "attach", "exec", "export", "remove", "credential"])
    parser.add_argument("name", nargs="?", default="swimfrancisco")
    parser.add_argument("--agent", choices=["codex", "claude", "shell"], default="codex")
    parser.add_argument("--template")
    args, command = parser.parse_known_args()
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]+", args.name):
        parser.error("name must use lowercase letters, digits, periods, and hyphens")
    if command and args.action != "exec":
        parser.error(f"unexpected arguments: {' '.join(command)}")
    if args.action == "credential":
        credential = json.loads(output("devenv", "--quiet", "shell", "--",
                                       "./node_modules/.bin/wrangler", "auth", "token", "--json"))
        token = credential.get("token", "")
        if credential.get("type") not in ("oauth", "api_token") or not token or any(c.isspace() for c in token):
            raise RuntimeError("Wrangler did not return a usable OAuth or API token")
        print(token)
        return
    template = args.template or ""
    state = ROOT / ".sandbox" / f"{args.name}.json"
    if args.action == "create":
        if state.exists():
            parser.error("this sandbox already has local state; attach or remove it first")
        existing = json.loads(output(SBX, "ls", "--json"))["sandboxes"]
        if any(sandbox["name"] == args.name for sandbox in existing):
            parser.error("this sandbox already exists; attach to it instead")
        run(SBX, "env", "create", *environment_args(args.name, args.agent, template), "--auto-approve")
        seed(args.name, args.agent, template)
    elif args.action == "seed":
        seed(args.name, args.agent, template)
    elif args.action == "attach":
        run(SBX, "run", "--name", args.name)
    elif args.action == "exec":
        command = command[1:] if command[:1] == ["--"] else command
        if not command:
            parser.error("exec requires a command after --")
        run(SBX, "exec", "-w", WORKSPACE, args.name, *command)
    elif args.action == "export":
        export(args.name)
    elif args.action == "remove":
        configuration = json.loads(state.read_text())
        run(SBX, "stop", args.name)
        export(args.name)
        run(SBX, "env", "rm", *environment_args(args.name, configuration["agent"],
                                               configuration["template"]), "--force")
        state.unlink()


if __name__ == "__main__":
    main()
