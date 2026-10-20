"""Credential boundaries: fake values only, never read the host Keychain."""
import importlib.util
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tomllib

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sandbox_launcher", ROOT / "scripts/sandbox.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_default_profile_has_no_secrets():
    profiles = tomllib.loads((ROOT / "secretspec.toml").read_text())["profiles"]
    assert "default" not in profiles
    assert set(profiles["jev"]) == {"TYPESAFE_API_KEY"}
    assert set(profiles["extraction"]) == {"OPENAI_API_KEY"}
    assert set(profiles["infrastructure"]) == set(launcher.INFRASTRUCTURE_KEYS)


@pytest.mark.parametrize("profile", ["jev", "extraction", "cloudflare"])
def test_proxy_grants_are_scoped_and_resolve_only_one_host_key(monkeypatch, profile):
    calls = []
    monkeypatch.setattr(launcher, "run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(launcher.shutil, "which", lambda _: "/a path/secretspec")
    monkeypatch.setattr(launcher, "proxy_environment", lambda _: {})
    launcher.grant("isolated-test", profile)
    command = calls[0]
    assert command[command.index("--sandbox") + 1] == "isolated-test"
    resolver = shlex.split(command[command.index("--command") + 1])
    selected_profile, key, domain = launcher.SECRET_PROFILES[profile]
    assert resolver[0] == "env"
    assert resolver[2] == "/a path/secretspec"
    assert resolver[resolver.index("--file") + 1] == str(ROOT / "secretspec.toml")
    assert resolver[resolver.index("get") + 1] == key
    assert resolver[resolver.index("--profile") + 1] == selected_profile
    assert resolver[resolver.index("--provider") + 1] == "keyring"
    assert "--no-verify" not in command
    assert calls[1][-2:] == ("--sandbox", "isolated-test")
    assert domain + ":443" in calls[1]


def test_terraform_requires_all_credentials_before_starting(monkeypatch):
    for key in launcher.INFRASTRUCTURE_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(launcher, "run", lambda *a, **k: pytest.fail("must not start"))
    with pytest.raises(SystemExit, match="sandbox-terraform"):
        launcher.terraform("test", ["plan"])


def test_terraform_transports_only_expected_keys_over_stdin(monkeypatch, tmp_path):
    credentials = {key: f"synthetic-{key}" for key in launcher.INFRASTRUCTURE_KEYS}
    for key, value in credentials.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("TYPESAFE_API_KEY", "synthetic-unrelated")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-unrelated")
    monkeypatch.setenv("TF_LOG", "TRACE")
    calls = []
    monkeypatch.setattr(launcher, "run", lambda *args, **kwargs: calls.append((args, kwargs)))
    launcher.terraform("test", ["version"])
    command, options = calls[-1]
    assert json.loads(options["input"]) == credentials
    assert all(value not in str(command) for value in credentials.values())
    wrapper = command[command.index("-c") + 1]
    # Execute the actual guest wrapper against a harmless fake Terraform.
    executable = tmp_path / "terraform"
    executable.write_text(f'''#!{sys.executable}
import os, sys
assert all(os.environ[k] == "synthetic-" + k for k in {launcher.INFRASTRUCTURE_KEYS!r})
assert all(k not in os.environ for k in ("TYPESAFE_API_KEY", "OPENAI_API_KEY", "TF_LOG"))
assert os.environ["TF_INPUT"] == "0"
assert sys.argv[1:] == ["-chdir=terraform", "version"]
assert sys.stdin.read() == ""
print("credential boundary passed")
''')
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    result = subprocess.run([sys.executable, "-c", wrapper, "version"], input=options["input"], capture_output=True, check=True)
    assert result.stdout == b"credential boundary passed\n"


def test_proxy_metadata_never_crosses_sandbox_or_domain_boundaries(monkeypatch):
    records = {"custom_secrets": [
        {"scope": "test", "env": "TYPESAFE_API_KEY", "targets": ["api.typesafe.ai"], "placeholder": "sbx-cs-good"},
        {"scope": "other", "env": "OPENAI_API_KEY", "targets": ["api.openai.com"], "placeholder": "sbx-cs-other"},
        {"scope": "test", "env": "OPENAI_API_KEY", "targets": ["unrelated.example"], "placeholder": "sbx-cs-wrong-host"},
    ]}
    monkeypatch.setattr(launcher, "output", lambda *args: json.dumps(records).encode())
    assert launcher.proxy_flags("test") == ["--env", "TYPESAFE_API_KEY=sbx-cs-good"]
    records["custom_secrets"].append(records["custom_secrets"][0])
    with pytest.raises(SystemExit, match="duplicate"):
        launcher.proxy_environment("test")
