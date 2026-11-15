import pytest

from buddy_github import (
    MAX_REPO_FILES,
    _is_review_candidate,
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
    assert not _is_review_candidate(
        {"type": "blob", "path": path, "size": 20}
    )


def test_accept_small_source_file_and_reject_large_or_nonfile_entries():
    assert _is_review_candidate(
        {"type": "blob", "path": "src/app.py", "size": 100}
    )
    assert not _is_review_candidate(
        {"type": "blob", "path": "src/app.py", "size": 6000}
    )
    assert not _is_review_candidate(
        {"type": "tree", "path": "src/app.py", "size": 100}
    )
    assert MAX_REPO_FILES == 12
