# Client development

`cli.py` owns generic grammar, validation, confirmations, SSH transport and safe output.
`billing_cli.py` and `billing_bot.py` own ledger interaction. `management_bot.py` owns
the generic Telegram handler; `operator_output.py` and `inbounds.py` provide shared
presentation. Clients never import application models or host implementations.

Extensions add parser groups through `cli.parser(extend=...)` and call `cli.main`
with a parser factory/request handler. Telegram extensions compose `command` with
an explicit dispatch callback. Keep host-specific commands outside this package.

Use Python 3.12+ for development (runtime supports 3.10+):

```sh
uv sync --frozen --extra dev
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv build
```

Test grammar/dispatch and confirmations without SSH/network access. Keep tests and
installation independent of application source. Profile and inbound-selection fixtures protect the public protocol.

## Dispatcher protocol

CLI requests travel through SSH (or local dispatch with `--local`):

```text
{"operation":"list","args":{"limit":20,"offset":0}}
```

The dispatcher returns JSON on stdout: `{"ok":true,"result":...}` or
`{"ok":false,"error":"..."}`. It must authorize callers, keep credentials on the
server and bridge account operations to Keyholder's authenticated API. The bot uses
a local dispatcher. The core API does not accept host-maintenance commands.

## CI and versions

`Admin package` checks tests, Ruff and package builds on pushes/PRs. Manual
`Prepare admin release` builds packages and creates a draft GitHub release with
checksums. Review the draft before publishing; neither workflow deploys services.

Client and core versions need not match. Preserve protocol-v1 operation names,
argument shapes and confirmations; test coordinated changes independently and
link their pull requests. Use versioned packages in production. Never include
deployment secrets or customer data in contributions.

## Updating an installed client

Install the reviewed wheel into the existing isolated environment, then check its
requirements:

```sh
/path/to/venv/bin/python -m pip install --no-index --no-deps --force-reinstall ./keyholder_admin-VERSION-py3-none-any.whl
/path/to/venv/bin/python -m pip check
```

Replace the environment path and filename. To build from a reviewed source checkout,
run `uv build`; alternatively, install that checkout with `python -m pip install .`
using the target environment's Python. Check compatibility with any installed
extensions before replacing the package, and retain the previous artifact for rollback.

The CLI uses the new package on its next invocation. A running Telegram bot must be
restarted through its service manager. Verify command help, a read-only account
request and `/ping`. Installation does not update the backend or dispatcher.
