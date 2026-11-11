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
installation independent of application source. Small profile/selection contracts
are snapshots of the public protocol, not a reason to import server internals.

## Dispatcher protocol

CLI requests travel through SSH (or local dispatch with `--local`):

```text
{"operation":"list","args":{"limit":20,"offset":0}}
```

The dispatcher returns JSON on stdout: `{"ok":true,"result":...}` or
`{"ok":false,"error":"..."}`. It must authorize callers, keep credentials on the
server and bridge account operations to Keyholder's authenticated API. The bot uses
a local dispatcher. Host maintenance belongs to private extensions, not the core API.

## CI and versions

`Admin package` checks tests, Ruff and package builds on pushes/PRs. Manual
`Prepare admin release` builds packages and creates a draft GitHub release with
checksums; it does not deploy. These workflows become available only after this
repository is published with Actions enabled. Review a draft before publishing.

Client and core versions need not match. Preserve protocol-v1 operation names,
argument shapes and confirmations; test coordinated changes independently and
link their pull requests. Install released packages in production, not sibling
source paths. Host source, deployment secrets and customer data stay outside this
repository. MIT applies to this package, not other projects' code.
