# Agents Tooling Specification — Python

Use this specification for a Python agent codebase. Copy it into the repository as `AGENTS.md`.

## 1. Tooling

Pin versions in `pyproject.toml`. Commit `uv.lock`. Install with `uv sync --locked`. Never ship a development tool to runtime.

**Development.** [uv](https://docs.astral.sh/uv/) dependencies, environments, and the lockfile · [ruff](https://docs.astral.sh/ruff/) lint and format · [ty](https://docs.astral.sh/ty/) types, pinned exactly while it stays in beta · [pytest](https://docs.pytest.org/) with [pytest-cov](https://pytest-cov.readthedocs.io/) tests, doctests, and coverage · [prek](https://prek.j178.dev/) hooks, with `prek.toml` · [commitizen](https://commitizen-tools.github.io/commitizen/) (`cz`) commits and SemVer bumps · [git-cliff](https://git-cliff.org/docs/) changelog.

**Runtime.** [Pydantic](https://pydantic.dev/) v2 validation · [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/) configuration · [FastAPI](https://fastapi.tiangolo.com/) async APIs, server only · [HTTPX2](https://github.com/pydantic/httpx2) HTTP client, imported as `httpx2` · [sqlite3](https://docs.python.org/3/library/sqlite3.html) stdlib database, no pin · [pandas](https://pandas.pydata.org/docs/) tables · [Typer](https://typer.tiangolo.com/) CLIs · [marimo](https://docs.marimo.io/) reactive notebooks · [structlog](https://www.structlog.org/) logging · [Altair](https://altair-viz.github.io/) and [Matplotlib](https://matplotlib.org/stable/) charts.

## 2. Standards

* [SemVer 2.0.0](https://semver.org/) for versions.
* [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) for commit messages.
* [Contributor Covenant 3.0](https://www.contributor-covenant.org/version/3/0/code_of_conduct/) as `CODE_OF_CONDUCT.md`.
* [AGPL-3.0](https://www.gnu.org/licenses/agpl-3.0.en.html) as `LICENSE`. SPDX identifier `AGPL-3.0-only`.

## 3. Code

* Use a type hint everywhere.
* Use Pydantic at an I/O boundary: an API, a tool, configuration, or serialized state.
* Use a dataclass for an internal carrier. Keep core logic in pure functions.
* Put a runnable example in each docstring.
* Require 100% coverage on core logic. Keep each exclusion narrow and explicit.
* Run the gate below through `prek`, with a `cz` `commit-msg` hook. Let `git-cliff` write the changelog.

```bash
ruff check . && ruff format --check .
ty check
pytest --doctest-modules --cov --cov-fail-under=100
```

## 4. GitHub Workflow

Topic branch and pull request, unless this file says `Git workflow: main`. No push access: `gh repo fork OWNER/REPO --clone`.

PR title: a Conventional Commit. One logical change per PR.

## 5. CI/CD Security

Follow [secure use of Actions](https://docs.github.com/en/actions/reference/security/secure-use).

* Set `permissions: contents: read` at the top level. Widen it per job only where a job needs more.
* Default the repository token to read: `gh api -X PUT repos/OWNER/REPO/actions/permissions/workflow -f default_workflow_permissions=read`.
* Pin an action to a full commit SHA. Verify the SHA against the upstream repository, not a fork. Let Dependabot bump it.
* Never check out fork code under `pull_request_target`. Prefer `workflow_run`, and treat its artifacts as untrusted.
* Never interpolate `github.event.*` into `run:`. Pass the value through `env:` and quote `"$VAR"`.
* Use OIDC and a short-lived cloud role. Do not store a long-lived secret. Keep a secret a scalar, never a JSON blob. Rotate it.
* Gate a deploy on an Environment with required reviewers. Prefer an environment secret over a repository secret.
* Do not use a self-hosted runner on a public repository.
* Cover `.github/workflows/**` in `CODEOWNERS`.
* Require the section 3 gate, CodeQL, and `dependency-review-action`. Run the same gate locally, so CI gives no surprise. On a private repository, confirm the plan covers CodeQL and dependency review first.

## 6. Browser and WASM

These rules apply only to Python that runs in a browser. A server target has no such limit.

* Ship pure Python, or a verified Pyodide or PyPI WASM wheel. Never ship a development tool.
* Every Runtime entry except FastAPI and HTTPX2 is a candidate. Check the version first.
* Do not use an OS socket, a subprocess, or a thread. Do not run FastAPI in a browser.
* Use `pyodide.http.pyfetch` or `pyxhr` for HTTP. Use HTTPX2 only with a tested custom transport.
