import base64

import pytest

import buddy_github
from buddy_github import (
    MAX_REPO_FILES,
    _is_review_candidate,
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
    assert not _is_review_candidate({"type": "blob", "path": path, "size": 20})


def test_accept_small_source_file_and_reject_large_or_nonfile_entries():
    assert _is_review_candidate({"type": "blob", "path": "src/app.py", "size": 100})
    assert not _is_review_candidate(
        {"type": "blob", "path": "src/app.py", "size": 6000}
    )
    assert not _is_review_candidate({"type": "tree", "path": "src/app.py", "size": 100})
    assert MAX_REPO_FILES == 12


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
        if endpoint.endswith("/git/trees/main"):
            return {
                "tree": [{"type": "blob", "path": "config.yml", "size": len(content)}]
            }
        return {"content": base64.b64encode(content.encode("utf-8")).decode("ascii")}

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
