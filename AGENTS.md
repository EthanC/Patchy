# AGENTS.md

Guidance for AI agents and contributors working on Patchy.

## What Patchy does

Patchy checks the current version of configured game titles on several platforms (Steam, Battle.net, PlayStation 5 "prospero", PlayStation 4 "orbis"), stores the last seen version in SQLite, and posts a Discord Components V2 message when a version changes. It runs once and exits, or checks each platform instance every `interval` minutes (its own, or the top-level default).

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
  __main__.py      CLI (argparse): run, platforms. Signal handling and the interval loop.
  config.py        EnvironmentSettings (PATCHY_* env vars) and FileSettings (config.toml); no setting is in both. PlatformSettings: one platform instance.
  client.py        HttpClient: niquests session with retries; raises FetchError / PayloadError only.
  database.py      SQLModel tables (TitleRecord, UpdateRecord) and the Database wrapper.
  errors.py        PatchyError hierarchy. Every expected failure is one of these.
  logs.py          Loguru sinks: stderr and optional loguru-discord forwarding.
  notifier.py      Notifier protocol, DiscordNotifier (discord-clyde, Components V2), and discord_notifier() for an instance's webhook.
  runner.py        build_platforms(), Schedule (when each instance is next due), and Runner: per-title check loop, persistence, and error containment.
  platforms/
    __init__.py    @register decorator and registry(), which auto-imports every module here.
    base.py        Platform ABC, Release, Update, UpstreamModel, OptionalText.
    steam.py       Steam via api.steamcmd.net, including changed depots.
    battlenet.py   Battle.net via blizztrack.com. Artwork comes from BlizzTrack fragments, named after games (FRAGMENTS).
    playstation.py Prospero (PS5) and Orbis (PS4) via prosperopatches.com / orbispatches.com.
tests/
  conftest.py      FakeClient (canned HTTP responses), temporary Database, make_platform fixture.
  fixtures/        Sample upstream responses, one file per endpoint.
```

## Platform instances

Each `[[platforms.<key>]]` table in `config.toml` is one instance: a `Platform` object with its own `PlatformSettings` (`name`, `enabled`, `webhook_url`, `titles`, plus platform options such as Steam's `branch`). A platform can have any number of instances.

- `Platform.instance` is the instance's `name`, defaulting to the platform `key`. `build_platforms()` rejects two instances of one platform with the same name, so a platform with several instances needs names.
- `Platform.label` is what logs show: the platform name, plus the instance in parentheses when it is named.
- State is per instance. `TitleRecord` is keyed by `(platform, instance, title_id)` and `UpdateRecord` stores the instance, so the same title in two instances is tracked and reported separately. Renaming an instance makes its titles new again.
- Notifiers are per instance. `Runner` asks `notifier_for(platform)` (default `discord_notifier`, which uses the instance's `webhook_url`) once per instance; `None` means updates are only logged.
- `enabled = false` skips that instance only. Instances with no titles are skipped too.
- Intervals are per instance. `Schedule` checks every instance immediately, then again after its `interval`, falling back to the top-level `interval`; `0` checks it once. The loop runs only the instances that are due and exits when none will be due again. `--once` ignores every interval.

## How a check works

1. `build_platforms()` validates and instantiates each enabled instance. `Platform.__init__` normalizes title IDs with `normalize_title_id()`; invalid IDs are logged and dropped.
2. `Runner.check()` calls `platform.fetch(title_id)`, which returns a `Release`.
3. If the title is unknown, it is stored without notifying. If the version is unchanged, only `last_checked` and `state` are updated.
4. If the version changed, `platform.enrich(release, previous_state)` adds notification-only data (artwork, Battle.net builds via `Release.build` / `previous_build`, Steam's changed depots), the instance's notifier sends the message, and only then is the new version stored together with an `UpdateRecord`. A failed notification therefore retries on the next run.

## Error handling rules

- Raise a `PatchyError` subclass for anything expected: `FetchError` (network or HTTP status), `PayloadError` (unexpected response shape), `TitleNotFoundError`, `ConfigError`, `StorageError`, `NotificationError`. Never let niquests, pydantic, or SQLAlchemy exceptions escape their module.
- The runner contains every error per title, so one failing title never stops the others. `StorageError` is the exception: it aborts the run because nothing more can be saved.
- `FetchError` is logged as a warning without a traceback because upstream outages are routine. Other errors are logged with their traceback.
- `enrich()` must not fail the update: catch `PatchyError` inside it, log a warning, and return what you have.
- Configuration errors are reported with every invalid key at once and exit with status 1.

## Adding a platform

1. Create `src/patchy/platforms/<name>.py`. No other file needs to change for the platform to be discovered.
2. Describe each upstream response with `UpstreamModel` subclasses (prefixed `_`, private to the module). Use `OptionalText` for optional strings that upstream may send as `""` or `false`. Fetch with `self.client.get_model(url, Model)`, which validates the response and raises `PayloadError` on mismatch.
3. If the platform needs options beyond `name`, `enabled`, `webhook_url`, and `titles`, subclass `PlatformSettings` and set `settings_model`. Options apply per instance.
4. Subclass `Platform[YourSettings]`, set `key` (lowercase, used in `config.toml` and the database, so never change it once released), `name`, `source` (the site `Release.url` links to, shown as "View on <source>"), `color`, and `icon_url`, then decorate with `@register`. Details are a single string (shown as code) or a tuple of entries (shown as a bulleted list). Set `proxy_media = True` if the host serves images Discord may not render (for example without a `Content-Type`), so they go through wsrv.nl.
5. Implement `fetch()` with the minimum requests needed to read the version. Put extra requests for notifications in `enrich()`. Override `normalize_title_id()` to reject or canonicalize IDs, and `display_title_id()` to change how notifications show them.
   To describe what changed between versions, set `Release.state` in `fetch()` to a JSON string from a private Pydantic model. Patchy stores it with the title and passes the previous one to `enrich()` as `previous_state`, which is `None` for titles stored before the platform set any; treat unreadable state as missing.
6. Add fixtures under `tests/fixtures/` and tests in `tests/test_platforms.py` using `client.serve(url, fixture)`. Update `test_registry_discovers_every_platform`.
7. Document the platform in `config.example.toml` and the README table.

```python
@register
class Example(Platform[PlatformSettings]):
    key: ClassVar[str] = "example"
    name: ClassVar[str] = "Example"
    source: ClassVar[str] = "Example.com"
    color: ClassVar[int] = 0x123456
    icon_url: ClassVar[str | None] = None

    @override
    def fetch(self: Self, title_id: str) -> Release:
        res: _Response = self.client.get_model(f"{API_URL}/{title_id}", _Response)

        return Release(title_id=title_id, name=res.name, version=res.version)
```

## Adding other features

- New notification targets implement the `Notifier` protocol in `notifier.py` and are wired up in `__main__._run()`.
- Every setting lives in exactly one place. Runtime behaviour (dry run, logging, database path, HTTP, the config path) goes on `EnvironmentSettings`, documented in `.env.example` and the README's variable table. What to watch and where to report it (the default interval, and per instance: titles, webhook, interval, platform options) goes on `FileSettings` or `PlatformSettings`, documented in `config.example.toml` and the README's option table. Never add a setting to both.
- Environment variables join the path with single underscores (`log.level` is `PATCHY_LOG_LEVEL`); only the first underscore after a section name splits, so environment settings nest at most one level deep. Unknown `PATCHY_*` variables, and variables for `config.toml` settings, are ignored. `FileSettings.load()` rejects unknown keys and reports environment settings found in `config.toml` with the variable to use instead. Cover new variables in `TestEnvironment.test_every_variable`.
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

## Commits

Write commit messages in [Conventional Commits](https://www.conventionalcommits.org/) style: `<type>[(scope)][!]: <description>`.

- Types: `feat`, `fix`, `refactor`, `perf`, `docs`, `test`, `build`, `ci`, `chore`, `style`, `revert`.
- Scope is optional: a platform key (`steam`, `battlenet`, `playstation`) or module (`config`, `notifier`, `runner`, `database`) when the change is confined to one.
- Mark changes that break existing configuration, environment variables, or stored data with `!`, and explain the migration in the body.
- The description is imperative and lowercase, with no trailing period. The body explains why.

## Docker and CI

- `Dockerfile` builds a uv virtual environment on `python:3.15-alpine` and copies it into a clean Alpine image. All dependencies have musllinux wheels, so no compiler is needed; check this before adding a compiled dependency.
- `docker-entrypoint.sh` runs Patchy as `PUID:PGID` (default `1000:1000`) using `su-exec`, and only re-owns `/data` and `patchy.db*`.
- `.github/workflows/ci.yaml` runs the checks, then builds `linux/amd64` and `linux/arm64` images and pushes them to `ghcr.io/<owner>/<repo>` on every push. `latest` tracks the default branch.
