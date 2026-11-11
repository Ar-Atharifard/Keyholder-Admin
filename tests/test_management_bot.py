from typing import Any

import pytest

from keyholder_admin import management_bot


def test_directory_only_returns_names_and_usernames(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        calls.append((operation, args))
        return [{"username": "alice", "name": "Alice Example"}]

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    assert management_bot.command('/directory 2 "Alice Example"', {}) == "alice | Alice Example"
    assert calls == [
        ("list", {"limit": 30, "offset": 30, "brief": True, "search": "Alice Example"})
    ]
    management_bot.command('/show "Alice Example"', {})
    assert calls[-1] == ("show", {"customer": "Alice Example"})
    management_bot.command('/customers "Alice Example"', {})
    assert calls[-1] == (
        "list",
        {"limit": 10, "offset": 0, "history": False, "search": "Alice Example"},
    )


def test_create_uses_allowlisted_dispatch_and_redacts_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> Any:
        calls.append((operation, args))
        return {
            "customer": {"id": "customer-id", "name": args["name"]},
            "token": "must-not-appear",
            "subscription_url": "https://example.invalid/s/must-not-appear",
        }

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    state: dict[str, Any] = {}
    output = management_bot.command(
        '/create opaque quota=10 days=30 protocols=vless,trojan name="Full Name"', state
    )
    assert calls[0][0] == "user-create"
    assert calls[0][1]["protocols"] == ["vless", "trojan"]
    assert calls[0][1]["name"] == "Full Name"
    assert "must-not-appear" not in output
    assert "customer-id" in output


def test_destructive_command_requires_matching_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> dict[str, str]:
        calls.append((operation, args))
        return {"status": "revoked"}

    monkeypatch.setattr(
        management_bot,
        "dispatch",
        dispatch,
    )
    state: dict[str, Any] = {}
    prompt = management_bot.command("/revoke alice", state)
    assert calls == []
    code = prompt.rsplit(" ", 1)[1]
    assert "revoked" in management_bot.command("/confirm " + code, state)
    assert calls == [("revoke", {"customer": "alice", "confirmed": True})]


def test_management_help_lists_explicit_private_link_commands() -> None:
    text = management_bot.help_text()
    assert "/link SELECTOR" in text
    assert "/config SELECTOR CONFIG_ID" in text
    assert "private administrator chat" in text


def test_help_describes_commands_and_distinguishes_global_inbound_list() -> None:
    text = management_bot.help_text()
    assert len(text) <= management_bot.MAX_MESSAGE
    assert "/inbounds — ALL available inbounds" in text
    assert "/inbounds USER — Open that user's selection picker" in text
    assert "omitted means default" in text
    assert "not panel username" in text
    for command in management_bot.BOT_COMMANDS:
        assert "/" + command["command"] in text
    for line in text.splitlines():
        if line.startswith("/"):
            assert " — " in line


def test_remap_requires_confirmation_and_can_be_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        management_bot,
        "dispatch",
        lambda operation, args: pytest.fail("dispatch must wait for confirmation"),
    )
    state: dict[str, Any] = {}
    assert "Confirm" in management_bot.command("/remap alice username=alice_new", state)
    assert state["pending"]["operation"] == "remap"
    assert management_bot.command("/cancel", state) == "Pending operation cancelled."
    assert "pending" not in state


def test_large_replies_are_split_without_losing_content(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []

    def telegram(token: str, method: str, values: dict[str, str]) -> dict[str, Any]:
        sent.append(values["text"])
        return {"ok": True}

    monkeypatch.setattr(management_bot, "telegram", telegram)
    text = "a" * 6000
    management_bot.send_reply("synthetic", 123456789, text)
    assert "".join(sent) == text
    assert all(len(page) <= management_bot.MAX_MESSAGE for page in sent)


def test_customer_inventory_paginates(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, Any]] = []

    def dispatch(operation: str, args: dict[str, Any]) -> list[Any]:
        calls.append(args)
        return []

    monkeypatch.setattr(management_bot, "dispatch", dispatch)
    management_bot.command("/customers 2", {})
    assert calls == [{"limit": 10, "offset": 10, "history": False}]


def test_expired_confirmation_never_dispatches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        management_bot, "dispatch", lambda *_: pytest.fail("expired confirmation dispatched")
    )
    state: dict[str, Any] = {
        "pending": {"code": "abcdef", "expires": 0, "operation": "revoke", "args": {}}
    }
    with pytest.raises(ValueError, match="expired"):
        management_bot.command("/confirm abcdef", state)


def test_missing_authorization_fields_fail_closed() -> None:
    assert not management_bot.authorized({}, 123)


def test_nested_secrets_are_redacted() -> None:
    assert management_bot.redact(
        {
            "users": [
                {
                    "name": "Alice",
                    "password": "secret",
                    "token": "secret",
                    "subscription_url": "secret",
                    "panel_url": "secret",
                }
            ]
        }
    ) == {"users": [{"name": "Alice"}]}


def test_telegram_rate_limit_retries_delivery_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import email.message
    import io
    import json
    import time
    import urllib.error
    import urllib.request

    delays: list[float] = []
    calls: list[object] = []

    class Response:
        def __enter__(self: Any) -> object:
            return io.BytesIO(b'{"ok":true,"result":{}}')

        def __exit__(self: Any, *args: object) -> None:
            pass

    class Opener:
        def open(self: Any, request: object, **kwargs: object) -> Response:
            calls.append(request)
            if len(calls) == 1:
                raise urllib.error.HTTPError(
                    "https://example.invalid",
                    429,
                    "rate limited",
                    email.message.Message(),
                    io.BytesIO(json.dumps({"parameters": {"retry_after": 2}}).encode()),
                )
            return Response()

    monkeypatch.setattr(urllib.request, "build_opener", lambda *_: Opener())
    monkeypatch.setattr(time, "sleep", delays.append)
    assert management_bot.telegram("synthetic", "sendMessage", {"text": "hello"})["ok"]
    assert len(calls) == 2 and delays == [2.1]


def test_link_commands_reject_wrong_arguments_and_oversized_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for text in ["/link", "/link alice extra", "/config alice", "/configs alice extra"]:
        with pytest.raises(ValueError):
            management_bot.command(text, {})
    monkeypatch.setattr(
        management_bot,
        "dispatch",
        lambda *args: {"subscription_url": "x" * (management_bot.MAX_MESSAGE + 1)},
    )
    with pytest.raises(ValueError, match="message size"):
        management_bot.command("/link alice", {})


def test_config_listing_is_readable_and_keeps_copyable_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        management_bot,
        "dispatch",
        lambda *a: {
            "configs": [
                {
                    "id": "abc123",
                    "name": "IR | REALITY | T1",
                    "protocol": "vless",
                    "transport": "tcp",
                    "security": "reality",
                    "ech": False,
                    "config_uri": "vless://private",
                }
            ]
        },
    )
    output = management_bot.command("/configs alice", {})
    assert "ID: abc123" in output and "Name: IR | REALITY | T1" in output
    assert "ECH enabled: No" in output
    assert "private" not in output and '"configs"' not in output
