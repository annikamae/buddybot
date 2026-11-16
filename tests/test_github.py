import base64

import pytest

import buddy_github
from buddy_github import (
    MAX_REPO_FILE_BYTES,
    MAX_REPO_FILES,
    _candidate_skip_reason,
    _review_priority,
    fetch_github_repository,
    parse_github_repo_url,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/owner/repository", ("owner", "repository")),
        ("https://github.com/owner/repository.git", ("owner", "repository")),
    ],
)
def test_parse_public_repository_url(url, expected):
    assert parse_github_repo_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "http://github.com/owner/repository",
        "https://github.com/owner/repository/tree/main",
        "https://user:password@github.com/owner/repository",
        "https://github.com/owner/repository?token=secret",
        "https://example.com/owner/repository",
    ],
)
def test_reject_noncanonical_repository_urls(url):
    with pytest.raises(ValueError):
        parse_github_repo_url(url)


@pytest.mark.parametrize(
    "path",
    [
        ".env",
        ".env.production",
        "config/private_key.pem",
        "src/id_rsa",
        "node_modules/package/index.js",
        "dist/app.js",
        "backup.p12",
    ],
)
def test_skip_generated_and_sensitive_files(path):
    assert (
        _candidate_skip_reason({"type": "blob", "path": path, "size": 20}) is not None
    )


def test_accept_small_source_file_and_reject_large_or_nonfile_entries():
    assert (
        _candidate_skip_reason({"type": "blob", "path": "src/app.py", "size": 100})
        is None
    )
    assert (
        _candidate_skip_reason({"type": "blob", "path": "src/app.py", "size": 6000})
        is None
    )
    assert (
        _candidate_skip_reason({"type": "tree", "path": "src/app.py", "size": 100})
        == "not_file"
    )
    assert (
        _candidate_skip_reason(
            {"type": "blob", "path": "src/app.py", "size": MAX_REPO_FILE_BYTES}
        )
        is None
    )
    assert (
        _candidate_skip_reason(
            {"type": "blob", "path": "src/app.py", "size": MAX_REPO_FILE_BYTES + 1}
        )
        == "oversized"
    )
    assert MAX_REPO_FILES == 50


@pytest.mark.parametrize(
    "path",
    [
        "requirements.txt",
        "package.json",
        "package-lock.json",
        "pyproject.toml",
        "Cargo.lock",
        "go.mod",
        "Gemfile",
        "Makefile",
    ],
)
def test_dependency_and_build_manifests_are_review_candidates(path):
    assert _candidate_skip_reason({"type": "blob", "path": path, "size": 100}) is None


def test_review_prioritizes_application_source_over_tests_and_docs():
    application = {
        "type": "blob",
        "path": "src/flask/app.py",
        "size": 100,
    }
    test = {"type": "blob", "path": "tests/test_app.py", "size": 100}
    docs = {"type": "blob", "path": "docs/conf.py", "size": 100}

    assert _review_priority(application) < _review_priority(test)
    assert _review_priority(application) < _review_priority(docs)


def test_repository_sample_redacts_common_credentials(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.headers = {}

        def close(self):
            pass

    content = (
        'api_key: "fake-api-value"\n'
        '{"github_token": "fake-token-value", "active": true}\n'
        "password = fake-password-value\n"
        "-----BEGIN PRIVATE KEY-----\nfake-private-key\n"
        "-----END PRIVATE KEY-----\n"
    )

    def fake_github_json(session, endpoint, params=None, limit=2_000_000):
        del session, params, limit
        if endpoint == "repos/owner/repo":
            return {"default_branch": "main"}
        if endpoint.endswith("/commits/main"):
            return {
                "sha": "a" * 40,
                "commit": {"tree": {"sha": "b" * 40}},
            }
        if endpoint.endswith("/git/trees/" + "b" * 40):
            return {
                "tree": [{"type": "blob", "path": "config.yml", "size": len(content)}]
            }
        return {
            "type": "file",
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
        }

    monkeypatch.setattr(buddy_github.requests, "Session", FakeSession)
    monkeypatch.setattr(buddy_github, "_github_json", fake_github_json)

    owner, repository, branch, files, notes = fetch_github_repository(
        "https://github.com/owner/repo"
    )

    assert (owner, repository, branch) == ("owner", "repo", "main")
    sampled = "\n".join(files)
    assert "fake-api-value" not in sampled
    assert "fake-token-value" not in sampled
    assert "fake-password-value" not in sampled
    assert "fake-private-key" not in sampled
    assert "[REDACTED]" in sampled
    assert any("Redacted likely credential values" in note for note in notes)


def test_truncated_recursive_tree_falls_back_to_directory_walk(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.headers = {}

        def close(self):
            pass

    calls = []

    def fake_github_json(session, endpoint, params=None, limit=2_000_000):
        del session, limit
        calls.append((endpoint, params))
        if endpoint == "repos/owner/repo":
            return {"default_branch": "main"}
        if endpoint.endswith("/commits/main"):
            return {
                "sha": "a" * 40,
                "commit": {"tree": {"sha": "b" * 40}},
            }
        if endpoint.endswith("/git/trees/" + "b" * 40):
            if params == {"recursive": "1"}:
                return {"tree": [], "truncated": True}
            return {"tree": [{"type": "tree", "path": "src", "sha": "c" * 40}]}
        if endpoint.endswith("/git/trees/" + "c" * 40):
            return {"tree": [{"type": "blob", "path": "app.py", "size": 10}]}
        assert endpoint.endswith("/contents/src/app.py")
        assert params == {"ref": "a" * 40}
        return {
            "type": "file",
            "content": base64.b64encode(b"print('safe')").decode("ascii"),
        }

    monkeypatch.setattr(buddy_github.requests, "Session", FakeSession)
    monkeypatch.setattr(buddy_github, "_github_json", fake_github_json)

    owner, repository, branch, files, notes = fetch_github_repository(
        "https://github.com/owner/repo"
    )

    assert (owner, repository, branch) == ("owner", "repo", "main")
    assert "src/app.py" in files[0]
    assert any("truncated" in note.lower() for note in notes)
    assert any("Reviewed commit:" in note for note in notes)
    assert len(calls) == 6


def test_repository_review_processes_more_than_twelve_files_and_reports_limit(
    monkeypatch,
):
    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.headers = {}

        def close(self):
            pass

    commit_sha = "a" * 40
    tree_sha = "b" * 40
    entries = [
        {"type": "blob", "path": f"src/file_{number}.py", "size": 4}
        for number in range(MAX_REPO_FILES + 3)
    ]

    def fake_github_json(session, endpoint, params=None, limit=2_000_000):
        del session, limit
        if endpoint == "repos/owner/repo":
            return {"default_branch": "main"}
        if endpoint.endswith("/commits/main"):
            return {
                "sha": commit_sha,
                "commit": {"tree": {"sha": tree_sha}},
            }
        if endpoint.endswith("/git/trees/" + tree_sha):
            return {"tree": entries}
        assert endpoint.startswith("repos/owner/repo/contents/")
        assert params == {"ref": commit_sha}
        return {
            "type": "file",
            "content": base64.b64encode(b"safe").decode("ascii"),
        }

    monkeypatch.setattr(buddy_github.requests, "Session", FakeSession)
    monkeypatch.setattr(buddy_github, "_github_json", fake_github_json)

    _, _, _, files, notes = fetch_github_repository("https://github.com/owner/repo")

    assert len(files) == MAX_REPO_FILES
    assert any(
        f"first {MAX_REPO_FILES} of {MAX_REPO_FILES + 3}" in note for note in notes
    )
