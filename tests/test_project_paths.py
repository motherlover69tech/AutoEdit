from pathlib import Path

import pytest

from autoedit.project_paths import PROJECT_SUBDIRS, create_project_tree, project_root


def test_create_project_tree_creates_spec_directories(tmp_path: Path):
    project_id = "01J00000000000000000000000"

    root = create_project_tree(tmp_path, project_id)

    assert root == tmp_path / project_id
    assert (root / "project.json").exists() is False
    for subdir in PROJECT_SUBDIRS:
        assert (root / subdir).is_dir(), subdir


@pytest.mark.parametrize(
    "bad_id",
    ["../escape", "01J0000000000000000000000/", "", "not-a-ulid", "01J0000000000000000000000."],
)
def test_project_root_rejects_unsafe_project_ids(tmp_path: Path, bad_id: str):
    with pytest.raises(ValueError):
        project_root(tmp_path, bad_id)
