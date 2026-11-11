#!/usr/bin/env python3
"""Manage Keyholder through SSH without exporting administrator credentials."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from keyholder_admin.profile_types import DEFAULT_PROFILES, SUPPORTED_KINDS

DEFAULT_KINDS = list(DEFAULT_PROFILES)
KINDS = list(SUPPORTED_KINDS)


def operator_config() -> dict[str, str]:
    configured = os.getenv("KEYHOLDER_ADMIN_CONFIG")
    path = (
        Path(configured)
        if configured
        else Path(__file__).resolve().parents[2] / ".private/admin.json"
    )
    if not path.exists():
        if configured:
            raise ValueError("Operator configuration file missing")
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or not all(isinstance(v, str) for v in data.values()):
        raise ValueError("Invalid operator configuration")
    return {str(k): str(v) for k, v in data.items()}


def remote_path() -> str:
    path = operator_config().get("remote_path", "/usr/local/lib/keyholder-admin/host.py")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in Path(path).parts:
        raise ValueError("Invalid remote dispatcher path")
    return path


def ssh_command() -> list[str]:
    command = ["ssh"]
    configured = operator_config().get("ssh_config")
    if configured:
        path = Path(configured).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError("Invalid SSH configuration path")
        command.extend(["-F", str(path)])
    return command


class CLIError(Exception):
    pass


class KeyholderParser(argparse.ArgumentParser):
    command_parsers: dict[tuple[str, ...], KeyholderParser]


COMMAND_HELP = {
    "config": "Retrieve one current configuration URI by its listed ID or unique family.",
    "backends": "List registered subscription backends without exposing credentials.",
    "backend-register": "Register the configured backend in Keyholder's backend registry.",
    "users": "List upstream Marzban users without credentials.",
    "inbounds": "List available upstream inbound tags by protocol.",
    "sync": "Register active upstream users that do not yet have a Keyholder customer.",
    "reconcile": "Rotate legacy canonical links and revoke duplicate registrations.",
    "user-create": "Provision a Marzban user and create one stable Keyholder subscription.",
    "user-update": "Change an upstream user's quota, expiry or enabled state.",
    "user-inbounds": "Show a numbered inbound picker or replace an explicit protocol selection.",
    "user-defaults": "View or change the inbound selection for future users.",
    "user-usage": "Read an upstream user's current traffic and plan state.",
    "user-reset-usage": "Reset an upstream user's traffic counter after confirmation.",
    "list": "List canonical Keyholder customers without subscription tokens.",
    "create": "Attach an existing active upstream user to one stable subscription.",
    "customer-update": "Update private identity metadata stored only by Keyholder.",
    "link": "Retrieve a customer's existing stable URL without creating a new one.",
    "configs": "List a customer's current connection configurations without credentials.",
    "show": "Show one canonical customer and its upstream mapping.",
    "check": "Check one customer's upstream profiles and rendered subscription.",
    "enable": "Resume Keyholder subscription delivery for a customer.",
    "disable": "Pause Keyholder subscription delivery for a customer.",
    "revoke": "Permanently revoke a customer registration after confirmation.",
    "rotate-token": "Replace a subscription token and invalidate the old URL.",
    "rename": "Change the private Keyholder display name without changing Marzban.",
    "remap": "Map a customer to a different upstream username without rotating its URL.",
    "profiles": "Set the rendered profile kinds for a customer override.",
}

GROUP_HELP = {
    "backend": "Manage subscription backend registrations.",
    "upstream": "Inspect and synchronize upstream panel resources.",
    "user": "Provision and manage upstream user accounts.",
    "customer": "Manage stable Keyholder customer registrations.",
}

from keyholder_admin import billing_cli  # noqa: E402

GROUP_HELP.update(billing_cli.GROUP_HELP)

LEGACY_COMMANDS = {
    "backends": ("backend", "list"),
    "backend-register": ("backend", "register"),
    "users": ("upstream", "users"),
    "inbounds": ("upstream", "inbounds"),
    "sync": ("upstream", "sync"),
    "reconcile": ("upstream", "reconcile"),
    "user-create": ("user", "create"),
    "create": ("user", "attach"),
    "user-update": ("user", "update"),
    "user-inbounds": ("user", "inbounds"),
    "user-usage": ("user", "usage"),
    "user-reset-usage": ("user", "reset-usage"),
    "list": ("customer", "list"),
    "customer-update": ("customer", "update"),
    "link": ("customer", "link"),
    "show": ("customer", "show"),
    "check": ("customer", "check"),
    "enable": ("customer", "enable"),
    "disable": ("customer", "disable"),
    "revoke": ("customer", "revoke"),
    "rotate-token": ("customer", "rotate-token"),
    "rename": ("customer", "rename"),
    "remap": ("customer", "remap"),
    "profiles": ("customer", "profiles"),
}


def normalize_argv(
    argv: list[str], *, aliases: dict[str, tuple[str, str]] | None = None
) -> list[str]:
    """Translate the previous flat CLI into the stable resource/action grammar."""
    aliases = LEGACY_COMMANDS if aliases is None else aliases
    normalized = list(argv)
    index = 0
    while index < len(normalized):
        value = normalized[index]
        if value in {"--host", "--backend"}:
            index += 2
            continue
        if value in {"--local", "--json", "--version", "-h", "--help"} or value.startswith(
            ("--host=", "--backend=")
        ):
            index += 1
            continue
        break
    if index >= len(normalized):
        return normalized
    if normalized[index] == "help" and index + 1 < len(normalized):
        replacement = aliases.get(normalized[index + 1])
        if replacement:
            normalized[index + 1 : index + 2] = replacement
        return normalized
    replacement = aliases.get(normalized[index])
    if replacement:
        normalized[index : index + 1] = replacement
    return normalized


def package_version() -> str:
    try:
        return importlib.metadata.version("keyholder-admin")
    except importlib.metadata.PackageNotFoundError:
        return "development"


def parser(*, extend: Any = None) -> KeyholderParser:
    p = KeyholderParser(
        description=__doc__,
        epilog=(
            "Use 'keyholder help RESOURCE ACTION' or "
            "'keyholder RESOURCE ACTION --help' for details.\n"
            "Examples:\n"
            "  keyholder user create customer_001 --quota-gb 20 --days 30 --inbounds default\n"
            "  keyholder customer link customer_001 --save-link ./customer_001.json\n"
            "  keyholder customer list"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {package_version()}")
    p.add_argument(
        "--host",
        default=operator_config().get("host", "keyholder-server"),
        help="SSH alias for administration",
    )
    p.add_argument("--local", action="store_true", help="Run on the VPS as root")
    p.add_argument("--json", action="store_true", help="JSON output for nonsecret results")
    p.add_argument(
        "--backend",
        dest="backend_id",
        default=os.getenv("KEYHOLDER_OPERATOR_BACKEND_ID", "marzban-default"),
        help="Backend namespace (default: %(default)s)",
    )
    resources = p.add_subparsers(dest="resource", required=True, metavar="RESOURCE")
    command_parsers: dict[tuple[str, ...], KeyholderParser] = {}

    def group(
        name: str, description: str | None = None
    ) -> tuple[KeyholderParser, argparse._SubParsersAction[KeyholderParser]]:
        text = description or GROUP_HELP[name]
        item = resources.add_parser(name, help=text, description=text)
        command_parsers[(name,)] = item
        actions = item.add_subparsers(dest="action", required=True, metavar="ACTION")
        return item, actions

    def leaf(
        resource: str,
        actions: argparse._SubParsersAction[KeyholderParser],
        action: str,
        operation: str,
        description: str | None = None,
    ) -> KeyholderParser:
        text = description or COMMAND_HELP[operation]
        item = actions.add_parser(action, help=text, description=text)
        item.set_defaults(operation=operation)
        command_parsers[(resource, action)] = item
        return item

    _, backend = group("backend")
    leaf("backend", backend, "list", "backends")
    leaf("backend", backend, "register", "backend-register")

    _, upstream = group("upstream")
    for action in ["users", "inbounds", "sync"]:
        leaf("upstream", upstream, action, action)
    reconcile = leaf("upstream", upstream, "reconcile", "reconcile")
    reconcile.add_argument("--confirm", action="store_true", dest="confirmed", help="Apply changes")

    _, user = group("user")
    user_create = leaf("user", user, "create", "user-create")
    user_create.add_argument("username", help="New Marzban username")
    user_create.add_argument("--name", help="Private customer name; defaults to username")
    user_create.add_argument("--telegram", help="Unique Telegram username or numeric ID")
    user_create.add_argument(
        "--phone", help="Unique international phone number, for example +98912..."
    )
    user_create.add_argument(
        "--quota-gb", type=float, required=True, help="0 explicitly means unlimited"
    )
    user_create.add_argument("--days", type=int, required=True, help="0 explicitly means no expiry")
    user_create.add_argument(
        "--protocols",
        nargs="+",
        choices=["vless", "vmess", "trojan", "shadowsocks"],
        help=argparse.SUPPRESS,
    )
    user_create.add_argument(
        "--inbounds", help="Comma-separated inbound numbers, all, or default (omitted: default)"
    )
    user_create.add_argument("--save-link", type=Path, help="New private JSON file for the URL")
    user_create.add_argument("--inbound-tags", nargs="+", help=argparse.SUPPRESS)

    attach = leaf("user", user, "attach", "create")
    attach.add_argument("username", help="Existing Marzban username")
    attach.add_argument("--name", help="Display name; defaults to Marzban username")
    attach.add_argument("--telegram", help="Unique Telegram username or numeric ID")
    attach.add_argument("--phone", help="Unique international phone number, for example +98912...")
    attach.add_argument("--profiles", nargs="+", choices=KINDS)
    attach.add_argument(
        "--save-link", type=Path, help="Explicit private local file, never overwritten"
    )

    user_update = leaf("user", user, "update", "user-update")
    user_update.add_argument("username", help="Marzban username")
    user_update.add_argument("--quota-gb", type=float, help="New quota; 0 means unlimited")
    user_update.add_argument("--days", type=int, help="Expiry from now; 0 means no expiry")
    user_update.add_argument("--status", choices=["active", "disabled"], help="Panel status")
    inbound = leaf("user", user, "inbounds", "user-inbounds")
    inbound.add_argument("username", nargs="?", help="Omit to list available inbounds")
    inbound.add_argument("--protocol", choices=["vless", "vmess", "trojan", "shadowsocks"])
    inbound.add_argument("--tags", nargs="*", help="Advanced: selected tags for --protocol")
    inbound.add_argument(
        "--select", help="Replace selection: comma-separated numbers, all, or default"
    )
    inbound.add_argument(
        "--confirm", action="store_true", dest="confirmed", help="Apply --select without prompting"
    )
    defaults = leaf("user", user, "defaults", "user-defaults")
    defaults.add_argument("--select", help="New defaults: comma-separated numbers or all")
    defaults.add_argument(
        "--confirm", action="store_true", dest="confirmed", help="Apply without prompting"
    )
    usage = leaf("user", user, "usage", "user-usage")
    usage.add_argument("username", help="Marzban username")
    reset = leaf("user", user, "reset-usage", "user-reset-usage")
    reset.add_argument("username", help="Marzban username")
    reset.add_argument("--confirm", action="store_true", dest="confirmed", help="Apply reset")

    _, customer = group("customer")
    listing = leaf("customer", customer, "list", "list")
    listing.add_argument("--limit", type=int, default=100, help="Rows, 1-100")
    listing.add_argument("--offset", type=int, default=0, help="Rows to skip")
    listing.add_argument("--history", action="store_true", help="Include revoked registrations")
    listing.add_argument("--brief", action="store_true", help="Only usernames and private names")
    listing.add_argument("--search", help="Filter username or private name (case-insensitive)")
    customer_update = leaf("customer", customer, "update", "customer-update")
    customer_update.add_argument(
        "customer", help="Customer ID, username, exact private name, Telegram or phone"
    )
    customer_update.add_argument("--name")
    customer_update.add_argument("--telegram")
    customer_update.add_argument("--phone")
    customer_update.add_argument("--clear-telegram", action="store_true")
    customer_update.add_argument("--clear-phone", action="store_true")
    for op in [
        "link",
        "configs",
        "config",
        "show",
        "check",
        "enable",
        "disable",
        "revoke",
        "rotate-token",
        "rename",
        "remap",
        "profiles",
    ]:
        command = leaf("customer", customer, op, op)
        command.add_argument(
            "customer", help="Customer ID, exact username/private name, Telegram handle/ID or phone"
        )
        if op == "config":
            command.add_argument("profile", help="Configuration ID or uniquely matching family")
        if op == "rename":
            command.add_argument("name", help="New private display name")
        if op == "remap":
            command.add_argument("username", help="Replacement upstream username")
        if op == "profiles":
            command.add_argument("profiles", nargs="+", choices=KINDS, help="Profile kinds")
        if op in {"revoke", "rotate-token"}:
            command.add_argument(
                "--confirm", action="store_true", dest="confirmed", help="Apply change"
            )
        if op == "link":
            command.add_argument("--info", action="store_true", help="Show the usage-page URL")
        if op in {"rotate-token", "link", "config"}:
            command.add_argument("--save-link", type=Path, help="New private JSON file")
    if extend is not None:
        extend(group, leaf)
    billing_cli.add_parsers(group, leaf)
    help_command = resources.add_parser(
        "help", help="Show complete help, or help for one resource/action path"
    )
    help_command.add_argument("command", nargs="*", metavar="COMMAND")
    help_command.set_defaults(operation="help")
    command_parsers[("help",)] = help_command
    p.command_parsers = command_parsers
    return p


def request(host: str, payload: dict[str, Any], local: bool = False) -> dict[str, Any]:
    command = (
        ["python3", remote_path()]
        if local
        else [
            *ssh_command(),
            "-o",
            "BatchMode=yes",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ConnectTimeout=10",
            host,
            "python3 " + remote_path(),
        ]
    )
    process = subprocess.run(
        command, input=json.dumps(payload).encode(), capture_output=True, timeout=75
    )
    try:
        envelope = json.loads(process.stdout)
    except ValueError:
        raise CLIError("SSH request failed; for mutations, check state before retrying.") from None
    if not envelope.get("ok"):
        raise CLIError(envelope.get("error", "Server operation failed."))
    return envelope  # type: ignore[no-any-return]


def safe(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)[1:-1]


def display(result: Any, as_json: bool) -> None:
    from keyholder_admin.operator_output import render

    if as_json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    elif isinstance(result, list) and all(
        isinstance(item, dict) and set(item) == {"username", "name"} for item in result
    ):
        for item in result:
            print(safe(item["username"]), safe(item["name"]), sep="\t")
    elif (
        isinstance(result, list)
        and result
        and all(isinstance(item, dict) and "mapping" in item for item in result)
    ):
        for item in result:
            print(
                safe(item["mapping"]["upstream_username"]),
                "\t".join(
                    safe(item.get(k, "")) for k in ["id", "telegram", "phone", "status", "name"]
                ),
                sep="\t",
            )
    else:
        print(render(result))


def pick_inbounds(args: argparse.Namespace, *, request_handler: Any = None) -> int:
    from keyholder_admin.inbounds import profile_label, profile_summary, select_tags

    request = request_handler or globals()["request"]
    base = {"username": getattr(args, "username", None), "backend_id": args.backend_id}

    def call(fields: dict[str, Any]) -> Any:
        return request(
            args.host, {"operation": args.operation, "args": {**base, **fields}}, local=args.local
        )["result"]

    catalog = call({})
    if args.json and args.select is None:
        display(catalog, True)
        return 0
    if not args.json:
        print("Available inbounds ([x] selected; default plan for an omitted username):")
        for row in catalog["entries"]:
            print(
                f"{row['number']:2}. [{'x' if row['selected'] else ' '}] "
                + profile_label(row)
                + f" ({row['protocol']})"
            )
        print("Selected: " + profile_summary([r for r in catalog["entries"] if r["selected"]]))
    selection = args.select
    if selection is None:
        if not sys.stdin.isatty() or not base["username"]:
            return 0
        selection = input("Select numbers separated by commas (Enter cancels): ").strip()
        if not selection:
            return 0
    try:
        selected = select_tags(catalog["entries"], selection, catalog.get("default_tags", []))
    except ValueError as error:
        raise CLIError(str(error)) from None
    chosen = [row for tag in selected for row in catalog["entries"] if row["tag"] == tag]
    if not args.json:
        print("New selection: " + "; ".join(profile_label(row) for row in chosen))
        print(profile_summary(chosen))
    if not args.confirmed:
        if not sys.stdin.isatty():
            raise CLIError("Use --confirm to apply a noninteractive selection.")
        if input("Apply this selection? [y/N] ").strip().lower() != "y":
            return 0
    display(
        call({"selected_tags": selected, "revision": catalog["revision"], "confirmed": True}),
        args.json,
    )
    return 0


def main(
    argv: list[str] | None = None, *, parser_factory: Any = None, request_handler: Any = None
) -> int:
    p = (parser_factory or parser)()
    request = request_handler or globals()["request"]
    supplied = list(sys.argv[1:] if argv is None else argv)
    args = p.parse_args(normalize_argv(supplied))
    if args.operation == "help":
        if args.command:
            path = tuple(args.command)
            command_parser = p.command_parsers.get(path)
            if command_parser is None:
                p.error("Unknown command path; use 'keyholder help' to list resources.")
            command_parser.print_help()
        else:
            p.print_help()
        return 0
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", args.host):
        p.error("Use an SSH alias without options, credentials or shell expressions.")
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", args.backend_id):
        p.error("Invalid backend ID.")
    if args.operation == "list" and (not 1 <= args.limit <= 100 or args.offset < 0):
        p.error("Limit must be 1–100 and offset must be nonnegative.")
    if (
        args.operation
        in {
            "create",
            "remap",
            "user-create",
            "user-update",
            "user-inbounds",
            "user-usage",
            "user-reset-usage",
        }
        and not (args.operation == "user-inbounds" and args.username is None)
        and not re.fullmatch(r"[A-Za-z0-9_]{3,32}", args.username)
    ):
        p.error("Marzban usernames must be 3–32 ASCII letters, digits or underscores.")
    if (
        args.operation in {"revoke", "rotate-token", "reconcile", "user-reset-usage"}
        and not args.confirmed
    ):
        p.error(
            "Use --confirm: revocation, token rotation and traffic reset are explicit operations."
        )
    if args.operation in {"create", "user-create"}:
        args.name = args.name or args.username
    if args.operation in {"create", "user-create", "rename"} and not 1 <= len(args.name) <= 200:
        p.error("Name must contain 1–200 characters.")
    if args.operation == "customer-update":
        if args.clear_telegram and args.telegram is not None:
            p.error("Use either --telegram or --clear-telegram.")
        if args.clear_phone and args.phone is not None:
            p.error("Use either --phone or --clear-phone.")
        if args.name is not None and not 1 <= len(args.name) <= 200:
            p.error("Name must contain 1–200 characters.")
        if not any(
            [
                args.name is not None,
                args.telegram is not None,
                args.phone is not None,
                args.clear_telegram,
                args.clear_phone,
            ]
        ):
            p.error("Specify at least one customer identity change.")
    if args.local and os.geteuid() != 0:
        p.error("--local requires root on the administration host.")
    if args.operation.startswith("billing-"):
        try:
            return billing_cli.run(args, request)
        except CLIError as error:
            print(str(error), file=sys.stderr)
            return 1
    if args.operation in {"user-create", "user-update"}:
        import math

        if args.quota_gb is not None and (not math.isfinite(args.quota_gb) or args.quota_gb < 0):
            p.error("Quota must be finite and nonnegative.")
        if args.days is not None and not 0 <= args.days <= 36500:
            p.error("Days must be 0–36500.")
        if args.operation == "user-update" and all(
            getattr(args, k) is None for k in ["quota_gb", "days", "status"]
        ):
            p.error("Specify at least one change.")
    secret = args.operation in {
        "create",
        "user-create",
        "link",
        "config",
        "rotate-token",
    }
    destination = getattr(args, "save_link", None)
    if secret and not destination and (not sys.stdout.isatty() or args.json):
        p.error("Links require an interactive terminal or explicit --save-link private file.")
    fd = None
    try:
        if args.operation == "user-defaults":
            return pick_inbounds(args, request_handler=request)
        if args.operation == "user-inbounds":
            if not args.username and (args.select or args.protocol or args.tags is not None):
                raise CLIError(
                    "Specify a username to edit, or use 'user defaults' for future users."
                )
            if bool(args.protocol) != (args.tags is not None) or (
                args.protocol and args.select is not None
            ):
                raise CLIError("Use --protocol with --tags, or the numbered picker.")
            if not args.protocol:
                return pick_inbounds(args, request_handler=request)
        if destination:
            fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        payload = {
            "operation": args.operation,
            "args": {
                k: v
                for k, v in vars(args).items()
                if k
                not in {
                    "operation",
                    "resource",
                    "action",
                    "command",
                    "host",
                    "json",
                    "save_link",
                    "local",
                    "info",
                }
            },
        }
        result = (
            request(args.host, payload, local=True) if args.local else request(args.host, payload)
        )["result"]
        if secret:
            if args.operation == "config":
                credentials = result
            else:
                credentials = {
                    "customer_id": result["customer"]["id"],
                    "subscription_url": result["subscription_url"],
                }
            if getattr(args, "info", False):
                credentials["usage_url"] = result["subscription_url"] + "?format=info"
            if fd is not None:
                with os.fdopen(fd, "w") as file:
                    fd = None
                    file.write(json.dumps(credentials, indent=2) + "\n")
                    file.flush()
                    os.fsync(file.fileno())
                print("Private link file saved. Keep it in secure storage.")
            elif args.operation == "config":
                print("Configuration:", result["name"])
                print("URI:", result["config_uri"])

                if not result["active"]:
                    print("Prepared only: public access is not active yet.")
            else:
                print("Customer ID:", result["customer"]["id"])
                if getattr(args, "info", False):
                    print("Usage URL:", credentials["usage_url"])
                else:
                    print("Subscription URL:", result["subscription_url"])
                print(
                    "Retrieve this same link later with keyholder link USER; rotation is explicit."
                )
        else:
            display(result, args.json)
        return 0
    except CLIError as error:
        print(str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, subprocess.SubprocessError):
        # A create/rotation may have succeeded even if its response was lost.
        print(
            "Operation failed. Check SSH, customer state and output permissions before retrying.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        return 130
    finally:
        if fd is not None:
            os.close(fd)
            assert destination is not None
            destination.unlink(missing_ok=True)


if __name__ == "__main__":
    raise SystemExit(main())
