import json
import sys
from pathlib import Path
from typing import Any

import pytest

from keyholder_admin import cli


def test_compact_list_output_only_has_username_and_name(capsys: pytest.CaptureFixture[str]) -> None:
    args = cli.parser().parse_args(["customer", "list", "--brief", "--search", "Alice"])
    assert args.brief and args.search == "Alice"
    cli.display([{"username": "alice", "name": "Alice Example"}], as_json=False)
    assert capsys.readouterr().out == "alice\tAlice Example\n"


def test_user_create_accepts_private_identity_fields() -> None:
    args = cli.parser().parse_args(
        [
            "user",
            "create",
            "opaque_01",
            "--name",
            "Full Name",
            "--telegram",
            "@handle",
            "--phone",
            "+989121234567",
            "--quota-gb",
            "10",
            "--days",
            "30",
            "--protocols",
            "vless",
        ]
    )
    assert args.name == "Full Name"
    assert args.telegram == "@handle"
    assert args.phone == "+989121234567"


def test_cli_refuses_secret_output_into_logs_before_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    with pytest.raises(SystemExit):
        cli.main(["create", "alice"])
    with pytest.raises(SystemExit):
        cli.main(["rotate-token", "alice", "--confirm"])


def test_cli_private_link_file_and_no_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = 0
    secret = "https://subscription.example/s/" + "synthetic-secret"

    def request(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return {"ok": True, "result": {"customer": {"id": "fixture"}, "subscription_url": secret}}

    monkeypatch.setattr(cli, "request", request)
    destination = tmp_path / "link.json"
    assert cli.main(["create", "alice", "--save-link", str(destination)]) == 0
    assert destination.stat().st_mode & 0o777 == 0o600
    assert json.loads(destination.read_text())["subscription_url"] == secret
    assert secret not in capsys.readouterr().out
    assert cli.main(["create", "alice", "--save-link", str(destination)]) == 1
    assert calls == 1


def test_failed_cli_request_removes_empty_reserved_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise cli.CLIError("Operation failed; check state before retrying.")

    monkeypatch.setattr(cli, "request", fail)
    path = tmp_path / "link.json"
    assert cli.main(["create", "alice", "--save-link", str(path)]) == 1
    assert not path.exists()


def test_cli_rejects_ssh_option_injection() -> None:
    with pytest.raises(SystemExit):
        cli.main(["--host=-oProxyCommand=bad", "customer", "list"])


def test_private_operator_config_can_select_ssh_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ssh = tmp_path / "config"
    ssh.write_text("Host test\n  HostName example.invalid\n")
    operator = tmp_path / "admin.json"
    operator.write_text(json.dumps({"ssh_config": str(ssh)}))
    monkeypatch.setenv("KEYHOLDER_ADMIN_CONFIG", str(operator))
    assert cli.ssh_command() == ["ssh", "-F", str(ssh)]


def test_command_extension_reuses_public_dispatch_without_mutating_registry(
    capsys: pytest.CaptureFixture[str],
) -> None:
    original = dict(cli.GROUP_HELP)
    calls = []

    def extend(group: Any, leaf: Any) -> None:
        _, actions = group("extension", "An independently supplied command group")
        leaf("extension", actions, "inspect", "extension-inspect", "Inspect extension state")

    def request(host: str, payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"ok": True, "result": {"healthy": True}}

    assert (
        cli.main(
            ["extension", "inspect"],
            parser_factory=lambda: cli.parser(extend=extend),
            request_handler=request,
        )
        == 0
    )
    assert calls[0]["operation"] == "extension-inspect"
    assert cli.GROUP_HELP == original
    assert "Healthy" in capsys.readouterr().out
