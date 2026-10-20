lazy from pathlib import Path

import pytest

from patchy.database import Database, TitleRecord
from patchy.errors import ConfigError
from patchy.migrate import import_renovate_history
from tests.conftest import FIXTURES


def test_imports_renovate_history(database: Database) -> None:
    database.save_title(TitleRecord(platform="steam", title_id="730", version="newer"))

    imported = import_renovate_history(FIXTURES / "renovate_history.json", database)

    assert imported == 3
    tracked = database.get_title("steam", "730")
    assert tracked is not None
    assert tracked.version == "newer", "existing titles are left alone"
    numeric = database.get_title("steam", "440")
    assert numeric is not None
    assert numeric.version == "19000000"
    assert database.get_title("battlenet", "wow") is not None
    assert database.get_title("playstation5", "PPSA01284") is not None


def test_rejects_unreadable_files(tmp_path: Path, database: Database) -> None:
    path = tmp_path / "history.json"
    path.write_text("[]", encoding="utf-8")

    with pytest.raises(ConfigError):
        import_renovate_history(path, database)
