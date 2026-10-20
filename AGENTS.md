# AGENTS.md

Guidance for AI agents and contributors working on Patchy.

## What Patchy does

Patchy checks the current version of configured game titles on several platforms (Steam, Battle.net, PlayStation 5 "prospero", PlayStation 4 "orbis"), stores the last seen version in SQLite, and posts a Discord Components V2 message when a version changes. It runs once and exits, or loops every `interval` minutes.

## Commands

Every change must pass all four checks before it is committed. CI runs the same commands and will not publish an image if any fail.

```sh
uv sync                    # install, including dev tools
uv run ruff format         # format
uv run ruff check          # lint (every rule enabled)
uv run ty check            # type check (every rule is an error)
uv run pytest              # tests; no network access needed
uv run patchy --help       # run the CLI
```

## Layout

```
src/patchy/
  __main__.py      CLI (argparse): run, import-history, platforms. Signal handling and the interval loop.
  config.py        Settings: config.toml + PATCHY_* env vars via pydantic-settings. [platforms.*] is TOML-only. PlatformSettings base.
  client.py        HttpClient: niquests session with retries; raises FetchError / PayloadError only.
  database.py      SQLModel tables (TitleRecord, UpdateRecord) and the Database wrapper.
  errors.py        PatchyError hierarchy. Every expected failure is one of these.
  logs.py          Loguru sinks: stderr and optional loguru-discord forwarding.
  migrate.py       Import of Renovate's history.json.
  notifier.py      Notifier protocol and DiscordNotifier (discord-clyde, Components V2).
  runner.py        Runner: per-title check loop, persistence, and error containment.
  platforms/
    __init__.py    @register decorator and registry(), which auto-imports every module here.
    base.py        Platform ABC, Release, Update, UpstreamModel, OptionalText.
    steam.py       Steam via api.steamcmd.net.
    battlenet.py   Battle.net via blizztrack.com.
    playstation.py Prospero (PS5) and Orbis (PS4) via prosperopatches.com / orbispatches.com.
tests/
  conftest.py      FakeClient (canned HTTP responses), temporary Database, make_platform fixture.
  fixtures/        Sample upstream responses, one file per endpoint.
```

## How a check works

1. `build_platforms()` instantiates each configured platform. `Platform.__init__` normalizes title IDs with `normalize_title_id()`; invalid IDs are logged and dropped.
2. `Runner.check()` calls `platform.fetch(title_id)`, which returns a `Release`.
3. If the title is unknown, it is stored without notifying. If the version is unchanged, only `last_checked` is updated.
4. If the version changed, `platform.enrich(release)` adds notification-only data (artwork, build names), the notifier sends the message, and only then is the new version stored together with an `UpdateRecord`. A failed notification therefore retries on the next run.

## Error handling rules

- Raise a `PatchyError` subclass for anything expected: `FetchError` (network or HTTP status), `PayloadError` (unexpected response shape), `TitleNotFoundError`, `ConfigError`, `StorageError`, `NotificationError`. Never let niquests, pydantic, or SQLAlchemy exceptions escape their module.
- The runner contains every error per title, so one failing title never stops the others. `StorageError` is the exception: it aborts the run because nothing more can be saved.
- `FetchError` is logged as a warning without a traceback because upstream outages are routine. Other errors are logged with their traceback.
- `enrich()` must not fail the update: catch `PatchyError` inside it, log a warning, and return what you have.
- Configuration errors are reported with every invalid key at once and exit with status 1.

## Adding a platform

1. Create `src/patchy/platforms/<name>.py`. No other file needs to change for the platform to be discovered.
2. Describe each upstream response with `UpstreamModel` subclasses (prefixed `_`, private to the module). Use `OptionalText` for optional strings that upstream may send as `""`. Fetch with `self.client.get_model(url, Model)`, which validates the response and raises `PayloadError` on mismatch.
3. If the platform needs options beyond `titles` and `enabled`, subclass `PlatformSettings` and set `settings_model`.
4. Subclass `Platform[YourSettings]`, set `key` (lowercase, used in config, env vars, and the database, so never change it once released), `name`, `color`, and `icon_url`, then decorate with `@register`.
5. Implement `fetch()` with the minimum requests needed to read the version. Put extra requests for notifications in `enrich()`. Override `normalize_title_id()` to reject or canonicalize IDs.
6. Add fixtures under `tests/fixtures/` and tests in `tests/test_platforms.py` using `client.serve(url, fixture)`. Update `test_registry_discovers_every_platform`.
7. Document the platform in `config.example.toml` and the README table.

```python
@register
class Example(Platform[PlatformSettings]):
    key: ClassVar[str] = "example"
    name: ClassVar[str] = "Example"
    color: ClassVar[int] = 0x123456
    icon_url: ClassVar[str | None] = None

    @override
    def fetch(self: Self, title_id: str) -> Release:
        res: _Response = self.client.get_model(f"{API_URL}/{title_id}", _Response)

        return Release(title_id=title_id, name=res.name, version=res.version)
```

## Adding other features

- New notification targets implement the `Notifier` protocol in `notifier.py` and are wired up in `__main__._run()`.
- New settings go on the relevant model in `config.py` with a default, then in `config.example.toml` and the README. Environment variables join the path with single underscores (`discord.webhook_url` is `PATCHY_DISCORD_WEBHOOK_URL`); only the first underscore after a section name splits, so settings nest at most one level deep and top-level fields must not start with a section name followed by `_`. Add new variables to `test_every_option_has_a_single_underscore_variable`. Platform settings (titles included) are read from `config.toml` only. `_KnownEnvironment` silently ignores `PATCHY_*` variables for platforms and for options that don't exist, so removing an option never breaks existing deployments; unknown keys in `config.toml` are still errors.
- New tables are SQLModel classes in `database.py`. `create_all()` creates missing tables but never alters existing ones, so changing a column needs a migration step.
- New commands are argparse subcommands in `__main__.py`.

## Conventions

- Python 3.15. Use modern syntax: PEP 695 generics and `type` aliases, `lazy` imports for names only used in annotations (ruff applies these automatically with `--fix --unsafe-fixes`), `match`, and `typing.override` on every override.
- Type every variable, parameter, and return, including `self: Self`. Avoid `Any` and `cast`; if one is unavoidable, keep it local and explain why.
- Compare optionals with `is None` / `is not None`, never by truthiness (ty enforces this).
- Google-style docstrings on public modules, classes, and functions.
- Log with Loguru f-strings, and attach tracebacks with `logger.opt(exception=e)`.
- Tests never touch the network. Use `FakeClient` and fixtures.
- Keep `uv.lock` in sync (`uv lock`) whenever dependencies change.

## Docker and CI

- `Dockerfile` builds a uv virtual environment on `python:3.15-alpine` and copies it into a clean Alpine image. All dependencies have musllinux wheels, so no compiler is needed; check this before adding a compiled dependency.
- `docker-entrypoint.sh` runs Patchy as `PUID:PGID` (default `1000:1000`) using `su-exec`, and only re-owns `/data` and `patchy.db*`.
- `.github/workflows/ci.yaml` runs the checks, then builds `linux/amd64` and `linux/arm64` images and pushes them to `ghcr.io/<owner>/<repo>` on every push. `latest` tracks the default branch.
