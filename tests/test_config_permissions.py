import json
import stat
from pathlib import Path

from bester_ytm.config import (
    ensure_private_dir,
    get_paths,
    load_oauth_client,
    set_private_file,
    write_private_json,
)


def test_private_dir_and_file_permissions(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    paths = get_paths()

    ensure_private_dir(paths.config_dir)
    write_private_json(paths.oauth_client, {"client_id": "id", "client_secret": "secret"})

    assert stat.S_IMODE(paths.config_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(paths.oauth_client.stat().st_mode) == 0o600
    assert load_oauth_client(paths.oauth_client) == ("id", "secret")


def test_google_oauth_client_nested_shape(tmp_path: Path) -> None:
    path = tmp_path / "oauth-client.json"
    path.write_text(
        json.dumps(
            {
                "installed": {
                    "client_id": "nested-id",
                    "client_secret": "nested-secret",
                }
            }
        ),
        encoding="utf-8",
    )
    set_private_file(path)

    assert load_oauth_client(path) == ("nested-id", "nested-secret")
