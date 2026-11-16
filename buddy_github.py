"""Read-only, bounded sampling of public GitHub repositories."""

import base64
import json
import re
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

import requests

GITHUB_API = "https://api.github.com"
MAX_REPO_FILES = 50
MAX_REPO_FILE_CHARS = 12000
MAX_REPO_FILE_BYTES = 32_000
MAX_REPO_CHARS = 100000
MAX_TREE_BYTES = 4_000_000
MAX_DIRECTORY_TREE_BYTES = 512_000
MAX_TREE_REQUESTS = 80
MAX_TREE_ENTRIES = 25000
SECRET_ASSIGNMENT = re.compile(
    r"(?im)(['\"]?[\w.-]*(?:api[_-]?key|access[_-]?token|"
    r"client[_-]?secret|password|passwd|secret|private[_-]?key|token)"
    r"[\w.-]*['\"]?\s*[:=]\s*['\"]?)[^,\r\n'\"]+['\"]?"
)
PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)

GITHUB_REVIEW_TYPES = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".php",
    ".html",
    ".css",
    ".java",
    ".c",
    ".h",
    ".cpp",
    ".cs",
    ".go",
    ".rs",
    ".rb",
    ".sh",
    ".sql",
    ".json",
    ".yaml",
    ".yml",
    ".xml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".properties",
    ".gradle",
    ".md",
}
IMPORTANT_REVIEW_FILES = {
    "cargo.lock",
    "cargo.toml",
    "composer.json",
    "composer.lock",
    "dockerfile",
    "gemfile",
    "gemfile.lock",
    "go.mod",
    "go.sum",
    "makefile",
    "package-lock.json",
    "package.json",
    "pipfile",
    "pipfile.lock",
    "pnpm-lock.yaml",
    "poetry.lock",
    "pyproject.toml",
    "requirements.txt",
    "uv.lock",
    "yarn.lock",
}


def parse_github_repo_url(url: str) -> tuple[str, str]:
    try:
        parsed = urlsplit(url.strip())
    except ValueError as error:
        raise ValueError("Enter a valid public GitHub repository URL.") from error
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Only public https://github.com/owner/repository links are supported."
        )

    parts = [part for part in parsed.path.strip("/").split("/") if part]
    if len(parts) != 2:
        raise ValueError(
            "Use the repository main URL, such as https://github.com/owner/repo."
        )
    owner, repository = parts
    if repository.endswith(".git"):
        repository = repository[:-4]
    valid_segment = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")
    if not valid_segment.fullmatch(owner) or not valid_segment.fullmatch(repository):
        raise ValueError("The GitHub owner or repository name is invalid.")
    return owner, repository


def _github_json(
    session: requests.Session,
    endpoint: str,
    params=None,
    limit: int = 2_000_000,
):
    with session.get(
        f"{GITHUB_API}/{endpoint}",
        params=params,
        timeout=(4, 12),
        allow_redirects=False,
        stream=True,
    ) as response:
        if 300 <= response.status_code < 400:
            raise ValueError("GitHub redirected the request; it was not followed.")
        if response.status_code == 404:
            raise ValueError("That repository or file was not found or is not public.")
        if response.status_code == 403:
            raise ValueError("GitHub rate-limited this request. Wait and try again.")
        response.raise_for_status()
        body = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            body.extend(chunk)
            if len(body) > limit:
                raise ValueError("GitHub returned more data than Buddy allows.")
        try:
            return json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("GitHub returned invalid JSON.") from error


def _candidate_skip_reason(entry: dict) -> str | None:
    path = entry.get("path")
    if entry.get("type") != "blob" or not isinstance(path, str):
        return "not_file"
    parts = PurePosixPath(path).parts
    basename = PurePosixPath(path).name.casefold()
    ignored_parts = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "vendor",
        "dist",
        "build",
        "target",
        "coverage",
        "__pycache__",
        "third_party",
        "secrets",
        ".secrets",
        "credentials",
    }
    sensitive_name = re.compile(
        r"(^|[._-])(secrets?|credentials?|tokens?|id_rsa|id_ed25519|private_key)([._-]|$)",
        re.IGNORECASE,
    )
    if basename.startswith(".env") or sensitive_name.search(basename):
        return "sensitive"
    if Path(basename).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".p8"}:
        return "sensitive"
    if ignored_parts.intersection(part.casefold() for part in parts):
        return "filtered"
    if (
        Path(path).suffix.lower() not in GITHUB_REVIEW_TYPES
        and basename not in IMPORTANT_REVIEW_FILES
    ):
        return "filtered"
    size = entry.get("size")
    if not isinstance(size, int) or size < 0:
        return "invalid_size"
    if size > MAX_REPO_FILE_BYTES:
        return "oversized"
    return None


def _review_priority(entry: dict) -> tuple[int, int, int, int, str]:
    path = PurePosixPath(entry["path"])
    parts = {part.casefold() for part in path.parts[:-1]}
    lower_name = path.name.casefold()
    support_path_parts = {
        "test",
        "tests",
        "testing",
        "docs",
        "doc",
        "examples",
        "example",
        "fixtures",
        "fixture",
        "benchmarks",
        "benchmark",
        "samples",
        "sample",
    }
    support_priority = int(
        bool(parts.intersection(support_path_parts))
        or lower_name.startswith(("test_", "tests_", "conftest"))
    )
    source_priority = (
        0
        if parts.intersection(
            {"src", "source", "lib", "app", "server", "backend", "frontend", "core"}
        )
        else 1
    )
    code_priority = (
        0
        if Path(lower_name).suffix
        in {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs", ".php"}
        else 1
    )
    manifest_priority = 0 if lower_name in IMPORTANT_REVIEW_FILES else 1
    return (
        support_priority,
        source_priority,
        code_priority,
        manifest_priority,
        entry["path"].casefold(),
    )


def _fetch_tree_entries(
    session: requests.Session,
    root: str,
    root_tree_sha: str,
) -> tuple[list[dict], list[str]]:
    tree = _github_json(
        session,
        f"{root}/git/trees/{quote(root_tree_sha, safe='')}",
        params={"recursive": "1"},
        limit=MAX_TREE_BYTES,
    )
    entries = tree.get("tree", [])
    if not isinstance(entries, list):
        raise ValueError("GitHub returned an invalid repository file list.")
    if not tree.get("truncated"):
        return entries, []

    notes = [
        "GitHub truncated its recursive file listing; Buddy tried a bounded "
        "directory-by-directory listing."
    ]
    collected: list[dict] = []
    pending = [("", root_tree_sha)]
    requests_made = 0
    entries_seen = 0
    visited_trees = set()
    while pending:
        prefix, tree_sha = pending.pop()
        if (prefix, tree_sha) in visited_trees:
            continue
        if requests_made >= MAX_TREE_REQUESTS:
            notes.append(
                f"Stopped directory traversal at Buddy's {MAX_TREE_REQUESTS}-request limit."
            )
            break
        visited_trees.add((prefix, tree_sha))
        try:
            subtree = _github_json(
                session,
                f"{root}/git/trees/{quote(tree_sha, safe='')}",
                limit=MAX_DIRECTORY_TREE_BYTES,
            )
        except (requests.RequestException, ValueError) as error:
            notes.append(
                "Directory traversal stopped after GitHub returned "
                f"{type(error).__name__}."
            )
            break
        requests_made += 1
        subtree_entries = subtree.get("tree", [])
        if not isinstance(subtree_entries, list):
            notes.append("Directory traversal stopped on an invalid GitHub tree.")
            break
        if subtree.get("truncated"):
            notes.append(
                "GitHub truncated a directory listing; some repository files "
                "could not be enumerated."
            )
        for entry in subtree_entries:
            if not isinstance(entry, dict):
                continue
            entries_seen += 1
            name = entry.get("path")
            if not isinstance(name, str) or name in {"", ".", ".."}:
                continue
            path = f"{prefix}/{name}" if prefix else name
            if entry.get("type") == "tree" and isinstance(entry.get("sha"), str):
                pending.append((path, entry["sha"]))
            elif entry.get("type") == "blob":
                collected.append({**entry, "path": path})
            if entries_seen >= MAX_TREE_ENTRIES:
                notes.append(
                    f"Stopped directory traversal at Buddy's {MAX_TREE_ENTRIES}-entry limit."
                )
                pending.clear()
                break

    if collected:
        return collected, notes
    notes.append(
        "Buddy fell back to the partial recursive listing because directory "
        "traversal did not return any files."
    )
    return entries, notes


def fetch_github_repository(url: str) -> tuple[str, str, str, list[str], list[str]]:
    """Fetch a bounded, read-only set of eligible files from a public repo."""
    owner, repository = parse_github_repo_url(url)
    safe_owner = quote(owner, safe="")
    safe_repository = quote(repository, safe="")
    root = f"repos/{safe_owner}/{safe_repository}"
    session = requests.Session()
    session.trust_env = False
    session.headers.update(
        {
            "Accept": "application/vnd.github+json",
            "User-Agent": "Buddy-Defensive-Review",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    try:
        info = _github_json(session, root, limit=256_000)
        branch = info.get("default_branch")
        if not isinstance(branch, str) or not branch:
            raise ValueError("GitHub did not report a default branch.")
        commit_info = _github_json(
            session,
            f"{root}/commits/{quote(branch, safe='')}",
            limit=512_000,
        )
        commit_sha = commit_info.get("sha")
        root_tree = commit_info.get("commit", {}).get("tree", {})
        root_tree_sha = root_tree.get("sha") if isinstance(root_tree, dict) else None
        if not isinstance(commit_sha, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40,64}", commit_sha
        ):
            raise ValueError("GitHub returned an invalid commit identifier.")
        if not isinstance(root_tree_sha, str) or not re.fullmatch(
            r"[0-9a-fA-F]{40,64}", root_tree_sha
        ):
            raise ValueError("GitHub returned an invalid repository tree identifier.")
        entries, notes = _fetch_tree_entries(session, root, root_tree_sha)
        notes.insert(0, f"Reviewed commit: {commit_sha[:12]}.")
        skip_counts: dict[str, int] = {}
        candidates = [
            entry
            for entry in entries
            if isinstance(entry, dict) and _candidate_skip_reason(entry) is None
        ]
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            reason = _candidate_skip_reason(entry)
            if reason:
                skip_counts[reason] = skip_counts.get(reason, 0) + 1
        candidates.sort(key=_review_priority)
        files = []
        used_chars = 0
        for entry in candidates[:MAX_REPO_FILES]:
            path = entry["path"]
            try:
                result = _github_json(
                    session,
                    f"{root}/contents/{quote(path, safe='/')}",
                    params={"ref": commit_sha},
                    limit=MAX_REPO_FILE_BYTES * 2 + 65536,
                )
                encoded = result.get("content", "")
                if result.get("type") != "file" or not isinstance(encoded, str):
                    notes.append(f"Skipped {path}: GitHub did not return text content.")
                    continue
                try:
                    content = base64.b64decode(
                        "".join(encoded.split()),
                        validate=True,
                    ).decode("utf-8", errors="replace")
                except (ValueError, UnicodeError):
                    notes.append(f"Skipped {path}: content was not valid base64 text.")
                    continue
                redacted = PRIVATE_KEY_BLOCK.sub("[REDACTED PRIVATE KEY]", content)
                redacted = SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", redacted)
                if redacted != content:
                    notes.append(
                        f"Redacted likely credential values in {path} before review."
                    )
                content = redacted
                remaining = MAX_REPO_CHARS - used_chars
                if remaining <= 0:
                    notes.append(
                        f"Stopped at Buddy's {MAX_REPO_CHARS:,}-character text limit."
                    )
                    break
                if len(content) > MAX_REPO_FILE_CHARS:
                    notes.append(
                        f"Truncated {path} to {MAX_REPO_FILE_CHARS:,} characters."
                    )
                content = content[: min(MAX_REPO_FILE_CHARS, remaining)]
                used_chars += len(content)
                files.append(f"--- Repository file: {path} ---\n{content}")
            except (requests.RequestException, ValueError) as error:
                notes.append(f"Skipped {path}: {type(error).__name__}.")
        if not files:
            raise ValueError(
                "Buddy could not find eligible public source or configuration files."
            )
        if len(candidates) > MAX_REPO_FILES:
            notes.append(
                f"Only the first {MAX_REPO_FILES} of {len(candidates)} eligible "
                "files were selected."
            )
        for reason, count in sorted(skip_counts.items()):
            if reason == "sensitive":
                notes.append(
                    f"Filtered {count} files with sensitive names or locations."
                )
            elif reason == "oversized":
                notes.append(
                    f"Skipped {count} eligible files larger than "
                    f"{MAX_REPO_FILE_BYTES // 1000} KB."
                )
            elif reason == "filtered":
                notes.append(f"Filtered {count} unsupported or generated files.")
            elif reason == "invalid_size":
                notes.append(f"Skipped {count} files with invalid size metadata.")
        return owner, repository, branch, files, notes
    finally:
        session.close()
