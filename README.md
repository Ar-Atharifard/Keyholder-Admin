# keyholder-admin

CLI and administrator-only Telegram client for
[Keyholder](https://github.com/Ar-Atharifard/keyholder). Manage accounts,
subscriptions, inbounds and billing through private access to the backend.

## Install and configure

Requires Python 3.10+ and SSH. Install a reviewed wheel in an isolated environment:

```sh
uv tool install ./keyholder_admin-0.2.0-py3-none-any.whl
```

Use the version you downloaded; verify its published checksum first. This command
does not assume the package is available on PyPI.

Create a private JSON file and select it explicitly:

```json
{"host":"vpn-admin","remote_path":"/usr/local/lib/keyholder-admin/host.py"}
```

```sh
chmod 600 /absolute/path/admin.json
export KEYHOLDER_ADMIN_CONFIG=/absolute/path/admin.json
keyholder help
keyholder user create --help
keyholder customer list
```

`host` is an existing SSH alias; optional `ssh_config` selects an absolute SSH
configuration file. Verify the server's host key. The server must already have a
compatible, authorized dispatcher at `remote_path`: this client does not install
one or grant privileges. No panel credentials belong in client configuration.

## Telegram

`keyholder-management-bot` uses an authorized **local** dispatcher. Supply these
through a protected service environment, not public configuration or shell history:

| Variable | Purpose |
| --- | --- |
| `KEYHOLDER_MANAGEMENT_BOT_TOKEN` | Bot token |
| `KEYHOLDER_MANAGEMENT_ADMIN_ID` | Allowed private administrator ID |
| `KEYHOLDER_MANAGEMENT_DISPATCHER` | Local dispatcher; defaults to `/usr/local/lib/keyholder-admin/host.py` |
| `KEYHOLDER_MANAGEMENT_STATE` | Private state file; defaults to `/var/lib/keyholder-management-bot/state.json` |

Use `/help` in the bot. Explicit link commands expose bearer credentials to that
administrator chat. Protect the Telegram account, token and state directory.

## Project boundaries

- **keyholder:** API, database, panel/account and billing rules.
- **keyholder-admin:** client grammar, transport, interaction and display.
- **keyholder-infra (private):** deployment, privileged dispatcher and operational extensions.

Repositories and versions are independent; no submodules are needed. This client
imports neither server code nor private infrastructure. Core 0.3.0 supplies the
protocol-v1 `/admin/operations` endpoint; verify compatibility with your dispatcher.
Uncertain mutations require checking state before retrying.

See [development and protocol](docs/development.md), [Contributing](CONTRIBUTING.md)
and [Security](SECURITY.md). Licensed under [MIT](LICENSE).
Developed with direct assistance from OpenAI Codex; maintainers review the result.
