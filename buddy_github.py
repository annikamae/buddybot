"""Read-only, bounded sampling of public GitHub repositories."""

import base64
import json
from pathlib import Path, PurePosixPath
import re
from urllib.parse import quote, urlsplit

import requests

GITHUB_API = "https://api.github.com"
MAX_REPO_FILES = 12
MAX_REPO_FILE_CHARS = 5000
MAX_REPO_CHARS = 30000
MAX_TREE_BYTES = 4_000_000

GITHUB_REVIEW_TYPES = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".php", ".html", ".css", ".java",
    ".c", ".h", ".cpp", ".cs", ".go", ".rs", ".rb", ".sh", ".sql", ".json",
    ".yaml", ".yml", ".xml", ".toml", ".ini", ".cfg", ".conf", ".properties",
    ".gradle", ".md",
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


def _is_review_candidate(entry: dict) -> bool:
    path = entry.get("path")
    if entry.get("type") != "blob" or not isinstance(path, str):
        return False
    parts = PurePosixPath(path).parts
    basename = PurePosixPath(path).name.casefold()
    ignored_parts = {
        ".git", ".venv", "venv", "node_modules", "vendor", "dist", "build",
        "target", "coverage", "__pycache__", "third_party",
    }
    sensitive_name = re.compile(
        r"(^|[._-])(secret|credentials?|token|id_rsa|id_ed25519|private_key)([._-]|$)",
        re.IGNORECASE,
    )
    if (
        basename.startswith(".env")
        or sensitive_name.search(basename)
        or Path(basename).suffix.lower() in {".pem", ".key", ".p12", ".pfx", ".p8"}
        or ignored_parts.intersection(part.casefold() for part in parts)
        or (
            Path(path).suffix.lower() not in GITHUB_REVIEW_TYPES
            and basename != "dockerfile"
        )
    ):
        return False
    size = entry.get("size")
    return isinstance(size, int) and 0 <= size <= MAX_REPO_FILE_CHARS


def fetch_github_repository(
    url: str,
) -> tuple[str, str, str, list[str], list[str]]:
    """Fetch a small, read-only sample of source/config files from a public repo."""
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
        tree = _github_json(
            session,
            f"{root}/git/trees/{quote(branch, safe='')}",
            params={"recursive": "1"},
            limit=MAX_TREE_BYTES,
        )
        entries = tree.get("tree", [])
        if not isinstance(entries, list):
            raise ValueError("GitHub returned an invalid repository file list.")
        candidates = [entry for entry in entries if isinstance(entry, dict) and _is_review_candidate(entry)]
        candidates.sort(
            key=lambda entry: (
                0
                if Path(entry["path"]).suffix.lower()
                in {".py", ".js", ".ts", ".tsx", ".java", ".go", ".rs", ".php"}
                else 1,
                entry["path"].count("/"),
                entry["path"].casefold(),
            )
        )
        files = []
        notes = []
        used_chars = 0
        for entry in candidates[:MAX_REPO_FILES]:
            path = entry["path"]
            try:
                result = _github_json(
                    session,
                    f"{root}/contents/{quote(path, safe='/')}",
                    params={"ref": branch},
                    limit=MAX_REPO_FILE_CHARS * 2,
                )
                encoded = result.get("content", "")
                if not isinstance(encoded, str):
                    notes.append(f"Skipped {path}: GitHub did not return text content.")
                    continue
                try:
                    content = base64.b64decode(encoded, validate=False).decode(
                        "utf-8", errors="replace"
                    )
                except (ValueError, UnicodeError):
                    notes.append(f"Skipped {path}: content was not valid base64 text.")
                    continue
                remaining = MAX_REPO_CHARS - used_chars
                if remaining <= 0:
                    notes.append("Stopped at Buddy’s repository text limit.")
                    break
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
            notes.append(f"Only the first {MAX_REPO_FILES} eligible files were selected.")
        if tree.get("truncated"):
            notes.append("GitHub marked the repository file listing as truncated.")
        return owner, repository, branch, files, notes
    finally:
        session.close()
