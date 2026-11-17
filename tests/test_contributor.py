import os
import subprocess
import sys

import pytest

import buddy_contributor
from buddy_contributor import (
    ContributorError,
    _validate_workspace_patch_paths,
    apply_patch,
    publish_draft_pull_request,
    sample_workspace,
    validate_patch,
)

VALID_PATCH = """\
diff --git a/src/app.py b/src/app.py
index 2c1f3a1..5d4e6f7 100644
--- a/src/app.py
+++ b/src/app.py
@@ -1 +1 @@
-print("unsafe")
+print("safer")
"""


def _git(path, *args):
    subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _workspace(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    (path / "src").mkdir()
    (path / "src" / "app.py").write_text('print("unsafe")\n', encoding="utf-8")
    _git(path, "init", "-q")
    _git(path, "config", "core.autocrlf", "false")
    _git(path, "config", "user.name", "Buddy Test")
    _git(path, "config", "user.email", "buddy@example.invalid")
    _git(path, "remote", "add", "origin", "https://github.com/example/repo.git")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "initial")
    base_branch = subprocess.run(
        ["git", "-C", str(path), "branch", "--show-current"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    _git(path, "switch", "-c", "buddy/test")
    return {
        "owner": "example",
        "repository": "repo",
        "workspace": str(path),
        "branch": "buddy/test",
        "base_branch": base_branch,
    }


def test_validate_patch_accepts_regular_unified_diff():
    assert validate_patch(VALID_PATCH).startswith("diff --git a/src/app.py")


@pytest.mark.parametrize(
    "patch",
    [
        VALID_PATCH.replace("a/src/app.py", "a/../outside.py"),
        VALID_PATCH.replace("b/src/app.py", "b/.github/workflows/ci.yml"),
        VALID_PATCH.replace("b/src/app.py", "b/.github/actions/build/action.yml"),
        VALID_PATCH.replace("b/src/app.py", "b/.env"),
        VALID_PATCH.replace(
            '+print("safer")',
            '+API_KEY = "hardcoded-example-secret"\n+print("safer")',
        ),
        VALID_PATCH.replace("index 2c1f3a1..5d4e6f7 100644\n", "new file mode 100755\n"),
        VALID_PATCH + "\nGIT binary patch",
        "```diff\n" + VALID_PATCH + "```",
    ],
)
def test_validate_patch_rejects_unsafe_or_unsupported_changes(patch):
    with pytest.raises(ContributorError):
        validate_patch(patch)


def test_apply_patch_stages_only_on_buddy_branch(tmp_path):
    workspace = _workspace(tmp_path)

    diff = apply_patch(workspace, VALID_PATCH)

    assert 'print("safer")' in (tmp_path / "repo" / "src" / "app.py").read_text(
        encoding="utf-8"
    )
    assert "print(\"safer\")" in diff
    status = subprocess.run(
        ["git", "-C", workspace["workspace"], "status", "--porcelain"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert status.startswith("M ")


def test_apply_patch_does_not_run_user_configured_git_filters(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    attributes = tmp_path / "repo" / ".gitattributes"
    attributes.write_text("src/*.py filter=buddytest\n", encoding="utf-8")
    _git(tmp_path / "repo", "add", ".gitattributes")
    _git(tmp_path / "repo", "commit", "-m", "add attributes")
    marker = tmp_path / "filter-ran.txt"
    filter_script = tmp_path / "global-filter.py"
    filter_script.write_text(
        "import pathlib, sys\n"
        f"pathlib.Path({str(marker)!r}).write_text('ran')\n"
        "sys.stdout.write(sys.stdin.read())\n",
        encoding="utf-8",
    )
    global_config = tmp_path / "global-git-config"
    python_executable = sys.executable.replace("\\", "/")
    global_config.write_text(
        f'[filter "buddytest"]\n clean = "{python_executable}" "{filter_script.as_posix()}"\n',
        encoding="utf-8",
    )
    filter_environment = os.environ.copy()
    filter_environment["GIT_CONFIG_GLOBAL"] = str(global_config)
    subprocess.run(
        [
            "git",
            "-C",
            workspace["workspace"],
            "hash-object",
            "--path=src/app.py",
            "--stdin",
        ],
        input="filter test\n",
        check=True,
        capture_output=True,
        text=True,
        env=filter_environment,
    )
    assert marker.exists()
    marker.unlink()
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))

    apply_patch(workspace, VALID_PATCH)

    assert not marker.exists()


def test_apply_patch_refuses_non_buddy_branch_and_does_not_change_file(tmp_path):
    workspace = _workspace(tmp_path)
    _git(tmp_path / "repo", "switch", workspace["base_branch"])

    with pytest.raises(ContributorError, match="Buddy's contribution branch"):
        apply_patch(workspace, VALID_PATCH)

    assert 'print("unsafe")' in (tmp_path / "repo" / "src" / "app.py").read_text(
        encoding="utf-8"
    )


def test_patch_path_validator_refuses_symlinked_parent(tmp_path):
    _workspace(tmp_path)
    repo = tmp_path / "repo"
    external = tmp_path / "outside"
    (repo / "src").rename(repo / "src-original")
    external.mkdir()
    try:
        (repo / "src").symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("This Windows environment does not allow creating directory symlinks.")

    with pytest.raises(ContributorError, match="symlink or a path outside"):
        _validate_workspace_patch_paths(repo, VALID_PATCH)


def test_sampling_redacts_credentials_and_excludes_secret_files(tmp_path):
    workspace = _workspace(tmp_path)
    config = tmp_path / "repo" / "src" / "config.py"
    (tmp_path / "repo" / ".env").write_text(
        "API_KEY=not-for-model\n",
        encoding="utf-8",
    )
    config.write_text('API_KEY = "fake-sample-key"\n', encoding="utf-8")

    files, notes = sample_workspace(workspace)

    assert any("Repository file: src/config.py" in file for file in files)
    assert all(".env" not in file for file in files)
    assert any("[REDACTED]" in file for file in files)
    assert any("Redacted likely credentials" in note for note in notes)


def test_publish_refuses_changes_different_from_the_reviewed_patch(tmp_path):
    workspace = _workspace(tmp_path)
    app_file = tmp_path / "repo" / "src" / "app.py"
    app_file.write_text('print("different")\n', encoding="utf-8")
    _git(tmp_path / "repo", "add", ".")

    with pytest.raises(ContributorError, match="differ from Buddy's displayed patch"):
        publish_draft_pull_request(workspace, "change app", VALID_PATCH)

    assert _git_output(tmp_path / "repo", "status", "--porcelain").startswith("M ")


def test_publish_refuses_a_changed_git_remote(tmp_path):
    workspace = _workspace(tmp_path)
    _git(
        tmp_path / "repo",
        "remote",
        "set-url",
        "origin",
        "https://github.com/someone-else/repo.git",
    )

    with pytest.raises(ContributorError, match="origin changed"):
        publish_draft_pull_request(workspace, "change app", VALID_PATCH)


def test_missing_github_cli_has_a_clear_setup_error(tmp_path, monkeypatch):
    monkeypatch.setattr(buddy_contributor.shutil, "which", lambda _: None)

    with pytest.raises(ContributorError, match="Install it from"):
        buddy_contributor.create_workspace(
            "https://github.com/owner/repository",
            tmp_path,
        )


def _git_output(path, *args):
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
