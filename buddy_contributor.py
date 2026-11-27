"""Local, review-first GitHub contribution workflow using GitHub CLI."""

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path, PurePosixPath

from buddy_github import (
    MAX_REPO_CHARS,
    MAX_REPO_FILE_BYTES,
    MAX_REPO_FILE_CHARS,
    MAX_REPO_FILES,
    PRIVATE_KEY_BLOCK,
    SECRET_ASSIGNMENT,
    _candidate_skip_reason,
    _review_priority,
    parse_github_repo_url,
)

MAX_REPOSITORY_KB = 250_000
MAX_PATCH_CHARS = 40_000
MAX_TASK_CHARS = 2_000
MAX_WORKSPACE_OUTPUT_CHARS = 200_000

# Windows-specific fallback: GitHub CLI is often installed to a fixed location
# but the running process's PATH may predate the install. Exposed as a module
# attribute so tests can point it at a nonexistent path.
_GITHUB_CLI_FALLBACK = Path("C:/Program Files/GitHub CLI/gh.exe")


class ContributorError(RuntimeError):
    """A safe, user-displayable GitHub contribution workflow error."""


def _require_cli() -> str:
    executable = shutil.which("gh")
    if not executable:
        # Windows-specific fallback: GitHub CLI is often installed to a fixed
        # location but the running process's PATH may predate the install.
        if _GITHUB_CLI_FALLBACK.exists():
            executable = str(_GITHUB_CLI_FALLBACK)
    if not executable:
        raise ContributorError(
            "GitHub CLI was not found. Install it from https://cli.github.com/, "
            "then run `gh auth login` in PowerShell."
        )
    return executable


def _git_environment(config_directory: Path) -> dict[str, str]:
    config_directory.mkdir(parents=True, exist_ok=True)
    hooks_directory = config_directory / "buddy-disabled-hooks"
    hooks_directory.mkdir(parents=True, exist_ok=True)
    safe_config = config_directory / "buddy-empty-git-config"
    safe_config.write_text("", encoding="utf-8")
    environment = os.environ.copy()
    environment["GIT_CONFIG_GLOBAL"] = str(safe_config)
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    environment["GIT_LFS_SKIP_SMUDGE"] = "1"
    environment["GIT_TERMINAL_PROMPT"] = "0"
    environment.pop("GIT_CONFIG_PARAMETERS", None)
    for index in range(10):
        environment.pop(f"GIT_CONFIG_KEY_{index}", None)
        environment.pop(f"GIT_CONFIG_VALUE_{index}", None)
    environment["GIT_CONFIG_COUNT"] = "3"
    environment["GIT_CONFIG_KEY_0"] = "credential.helper"
    environment["GIT_CONFIG_VALUE_0"] = ""
    environment["GIT_CONFIG_KEY_1"] = "credential.helper"
    environment["GIT_CONFIG_VALUE_1"] = "!gh auth git-credential"
    environment["GIT_CONFIG_KEY_2"] = "core.hooksPath"
    environment["GIT_CONFIG_VALUE_2"] = str(hooks_directory)
    return environment


def _run(
    arguments: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int = 30,
) -> str:
    command = arguments[0]
    if command == "gh":
        executable = _require_cli()
    elif command == "git":
        executable = shutil.which("git")
    else:
        raise ContributorError("Buddy attempted to run an unsupported command.")
    if not executable:
        raise ContributorError("Git was not found. Install Git for Windows and retry.")
    try:
        result = subprocess.run(
            [executable, *arguments[1:]],
            cwd=cwd,
            env=env,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ContributorError(
            f"The {command} command timed out. Check your connection and retry."
        ) from error
    except OSError as error:
        raise ContributorError(
            f"Could not start {command}: {type(error).__name__}."
        ) from error

    output = (result.stdout or "").strip()
    if result.returncode:
        details = (result.stderr or output).strip().replace("\r", " ").replace("\n", " ")
        details = details[:400] or "The command failed without details."
        raise ContributorError(f"{command} failed: {details}")
    return output


def _git(workspace: Path, *arguments: str, timeout: int = 30) -> str:
    return _run(
        [
            "git",
            "-C",
            str(workspace),
            *arguments,
        ],
        cwd=workspace,
        env=_git_environment(workspace.parent),
        timeout=timeout,
    )


def _canonical_remote(remote: str) -> tuple[str, str]:
    ssh_match = re.fullmatch(
        r"git@github\.com:([A-Za-z0-9_.-]{1,100})/"
        r"([A-Za-z0-9_.-]{1,100}?)(?:\.git)?",
        remote.strip(),
        re.IGNORECASE,
    )
    if ssh_match:
        return ssh_match.group(1).casefold(), ssh_match.group(2).casefold()
    try:
        return tuple(part.casefold() for part in parse_github_repo_url(remote))
    except ValueError as error:
        raise ContributorError(
            "The cloned repository did not have a supported GitHub origin."
        ) from error


def create_workspace(repository_url: str, workspace_root: Path) -> dict[str, str]:
    """Clone an authorized repository and create a clean Buddy branch."""
    owner, repository = parse_github_repo_url(repository_url)
    _require_cli()
    try:
        _run(["gh", "auth", "status", "--hostname", "github.com"], timeout=20)
        size = int(
            _run(
                [
                    "gh",
                    "api",
                    f"repos/{owner}/{repository}",
                    "--jq",
                    ".size",
                ],
                timeout=30,
            )
        )
    except ValueError as error:
        raise ContributorError(
            "GitHub did not return valid repository-size metadata."
        ) from error

    if size < 0 or size > MAX_REPOSITORY_KB:
        raise ContributorError(
            f"This repository is larger than Buddy's {MAX_REPOSITORY_KB // 1000} MB "
            "checkout limit."
        )

    base_branch = _run(
        [
            "gh",
            "api",
            f"repos/{owner}/{repository}",
            "--jq",
            ".default_branch",
        ],
        timeout=30,
    )
    if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", base_branch) or ".." in base_branch:
        raise ContributorError("GitHub returned an invalid default-branch name.")

    workspace_root = Path(workspace_root).resolve()
    workspace_root.mkdir(parents=True, exist_ok=True)
    identity = _run(
        [
            "gh",
            "api",
            "user",
            "--jq",
            r'"\(.id)+\(.login)@users.noreply.github.com"',
        ],
        timeout=30,
    )
    if not re.fullmatch(r"[0-9]+\+[A-Za-z0-9-]+@users\.noreply\.github\.com", identity):
        raise ContributorError("GitHub did not return a valid commit identity.")
    login = identity.split("+", 1)[1].split("@", 1)[0]
    author_name = f"Buddy ({login})"
    workspace = workspace_root / (
        f"{owner}-{repository}-{uuid.uuid4().hex[:10]}"
    )
    environment = _git_environment(workspace_root)
    try:
        result = subprocess.run(
            [
                _require_cli(),
                "repo",
                "clone",
                f"{owner}/{repository}",
                str(workspace),
                "--no-upstream",
                "--",
                "--depth=1",
                "--no-tags",
            ],
            cwd=workspace_root,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            shell=False,
        )
    except subprocess.TimeoutExpired as error:
        raise ContributorError(
            "Repository checkout timed out. Check the repository size and retry."
        ) from error
    except OSError as error:
        raise ContributorError(
            f"Could not start GitHub CLI: {type(error).__name__}."
        ) from error
    if result.returncode:
        details = (result.stderr or result.stdout or "").strip()
        details = details.replace("\r", " ").replace("\n", " ")[:400]
        raise ContributorError(
            "Could not check out this repository. Confirm your GitHub access and "
            f"try again. {details}"
        )

    workspace = workspace.resolve()
    actual_remote = _canonical_remote(_git(workspace, "remote", "get-url", "origin"))
    if actual_remote != (owner.casefold(), repository.casefold()):
        raise ContributorError("The clone's GitHub origin did not match the requested repository.")
    if _git(workspace, "status", "--porcelain"):
        raise ContributorError("The new repository checkout was not clean; it was not modified.")

    _git(workspace, "config", "user.name", author_name)
    _git(workspace, "config", "user.email", identity)
    branch = f"buddy/{uuid.uuid4().hex[:12]}"
    _git(workspace, "switch", "--create", branch)
    return {
        "owner": owner,
        "repository": repository,
        "workspace": str(workspace),
        "branch": branch,
        "base_branch": base_branch,
        "author_name": author_name,
        "author_email": identity,
    }


def _safe_patch_path(path: str) -> bool:
    if (
        not path
        or path.startswith(("/", "\\"))
        or "\\" in path
        or ":" in path
        or "\x00" in path
    ):
        return False
    raw_parts = path.split("/")
    if any(part in {"", ".", ".."} for part in raw_parts):
        return False
    parts = PurePosixPath(path).parts
    if any(part.casefold() == ".git" for part in parts):
        return False
    lowered_parts = [part.casefold() for part in parts]
    if len(lowered_parts) >= 2 and lowered_parts[:2] in (
        [".github", "workflows"],
        [".github", "actions"],
    ):
        return False
    if _candidate_skip_reason({"type": "blob", "path": path, "size": 0}) is not None:
        return False
    return True


def validate_patch(patch: str) -> str:
    """Reject model output that is malformed or can alter protected paths."""
    patch = patch.strip()
    if not patch or len(patch) > MAX_PATCH_CHARS:
        raise ContributorError(
            f"The generated patch is empty or exceeds {MAX_PATCH_CHARS:,} characters."
        )
    if "\x00" in patch or "GIT binary patch" in patch:
        raise ContributorError("Binary patches are not supported.")
    if PRIVATE_KEY_BLOCK.search(patch) or any(
        line.startswith("+")
        and not line.startswith("+++")
        and SECRET_ASSIGNMENT.search(line)
        for line in patch.splitlines()
    ):
        raise ContributorError(
            "The patch may contain a credential or private key. Remove it before continuing."
        )
    for line in patch.splitlines():
        if line.startswith(("old mode ", "new mode ", "rename ", "copy ")):
            raise ContributorError("Mode changes, renames, and copies are not supported.")
        if line.startswith(("new file mode ", "deleted file mode ")) and line not in {
            "new file mode 100644",
            "deleted file mode 100644",
        }:
            raise ContributorError("Only ordinary non-executable files can be added or deleted.")
    if "\n```" in patch or patch.startswith("```"):
        raise ContributorError("The response must contain only a unified diff, without code fences.")

    found_old = False
    found_new = False
    found_file = False
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", line)
            if not match or not all(_safe_patch_path(path) for path in match.groups()):
                raise ContributorError("The patch contains an unsafe or unsupported file path.")
            found_file = True
        elif line.startswith("--- "):
            path = line[4:].split("\t", 1)[0]
            if path != "/dev/null":
                if not path.startswith("a/") or not _safe_patch_path(path[2:]):
                    raise ContributorError("The patch contains an unsafe old-file path.")
            found_old = True
            found_file = True
        elif line.startswith("+++ "):
            path = line[4:].split("\t", 1)[0]
            if path != "/dev/null":
                if not path.startswith("b/") or not _safe_patch_path(path[2:]):
                    raise ContributorError("The patch contains an unsafe new-file path.")
            found_new = True
            found_file = True

    if not found_file or not found_old or not found_new:
        raise ContributorError("Buddy did not produce a valid unified diff.")
    return patch + "\n"


def _validate_workspace_patch_paths(workspace: Path, patch: str) -> None:
    root = workspace.resolve()
    targets = {
        line[4:].split("\t", 1)[0][2:]
        for line in patch.splitlines()
        if line.startswith("--- a/") or line.startswith("+++ b/")
    }
    for path in targets:
        candidate = root
        for part in path.split("/"):
            candidate = candidate / part
            try:
                if candidate.is_symlink() or not candidate.resolve().is_relative_to(root):
                    raise ContributorError(
                        "The patch targets a symlink or a path outside the local workspace."
                    )
            except OSError as error:
                raise ContributorError(
                    "Buddy could not safely resolve a patch target in the workspace."
                ) from error


def sample_workspace(workspace_info: dict[str, str]) -> tuple[list[str], list[str]]:
    """Return bounded, redacted source samples without executing repository code."""
    workspace = Path(workspace_info["workspace"]).resolve()
    if not workspace.is_dir():
        raise ContributorError("The local contribution workspace no longer exists.")
    raw_paths = _git(
        workspace,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "-z",
        timeout=30,
    )
    paths = sorted({item for item in raw_paths.split("\x00") if item})
    entries = []
    for path in paths:
        if not _safe_patch_path(path):
            continue
        candidate = workspace / Path(path)
        try:
            if not candidate.is_file() or candidate.is_symlink():
                continue
            size = candidate.stat().st_size
        except OSError:
            continue
        entry = {"type": "blob", "path": path, "size": size}
        if _candidate_skip_reason(entry) is None:
            entries.append(entry)

    entries.sort(key=_review_priority)
    notes = []
    candidates = entries[:MAX_REPO_FILES]
    if len(entries) > MAX_REPO_FILES:
        notes.append(f"Only {MAX_REPO_FILES} of {len(entries)} eligible files were sampled.")

    files = []
    used_chars = 0
    root = workspace.resolve()
    for entry in candidates:
        path = entry["path"]
        candidate = workspace / Path(path)
        try:
            if not candidate.resolve().is_relative_to(root) or candidate.is_symlink():
                notes.append(f"Skipped {path}: path is outside the workspace or is a symlink.")
                continue
            raw_content = candidate.read_bytes()
        except OSError:
            notes.append(f"Skipped {path}: file could not be read.")
            continue
        if len(raw_content) > MAX_REPO_FILE_BYTES:
            notes.append(f"Skipped {path}: file exceeded the {MAX_REPO_FILE_BYTES:,}-byte limit.")
            continue
        content = raw_content.decode("utf-8", errors="replace")
        redacted = PRIVATE_KEY_BLOCK.sub("[REDACTED PRIVATE KEY]", content)
        redacted = SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", redacted)
        if redacted != content:
            notes.append(f"Redacted likely credentials in {path} before sending it to the model.")
        content = redacted[: min(MAX_REPO_FILE_CHARS, MAX_REPO_CHARS - used_chars)]
        if len(content) < len(redacted):
            notes.append(f"Truncated {path} to Buddy's source-sampling limits.")
        if not content:
            break
        files.append(f"--- Repository file: {path} ---\n{content}")
        used_chars += len(content)
        if used_chars >= MAX_REPO_CHARS:
            notes.append(f"Stopped at Buddy's {MAX_REPO_CHARS:,}-character sample limit.")
            break
    if not files:
        notes.append("No eligible text source files were available; Buddy can still suggest new files.")
    return files, notes


def apply_patch(workspace_info: dict[str, str], patch: str) -> str:
    """Apply and stage a validated patch only when the checkout is otherwise clean."""
    workspace = Path(workspace_info["workspace"]).resolve()
    if not workspace.is_dir():
        raise ContributorError("The local contribution workspace no longer exists.")
    if _git(workspace, "branch", "--show-current") != workspace_info["branch"]:
        raise ContributorError("The workspace is no longer on Buddy's contribution branch.")
    if _git(workspace, "status", "--porcelain"):
        raise ContributorError(
            "The workspace has other changes. Buddy will not overwrite or stage them."
        )
    safe_patch = validate_patch(patch)
    _validate_workspace_patch_paths(workspace, safe_patch)
    # Pass the patch on stdin so it is never interpreted by a shell.
    git = shutil.which("git")
    if not git:
        raise ContributorError("Git was not found. Install Git for Windows and retry.")
    apply_command = [
        git,
        "-C",
        str(workspace),
        "-c",
        f"core.hooksPath={workspace.parent / 'buddy-disabled-hooks'}",
        "apply",
    ]
    try:
        checked = subprocess.run(
            [*apply_command, "--check", "--whitespace=nowarn", "-"],
            input=safe_patch,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_environment(workspace.parent),
            timeout=30,
            shell=False,
        )
        if checked.returncode:
            details = (checked.stderr or checked.stdout).strip().replace("\n", " ")[:400]
            raise ContributorError(f"Git rejected the patch: {details}")
        applied = subprocess.run(
            [*apply_command, "--whitespace=nowarn", "-"],
            input=safe_patch,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=_git_environment(workspace.parent),
            timeout=30,
            shell=False,
        )
        if applied.returncode:
            details = (applied.stderr or applied.stdout).strip().replace("\n", " ")[:400]
            raise ContributorError(f"Git could not apply the patch: {details}")
    except subprocess.TimeoutExpired as error:
        raise ContributorError("Applying the patch timed out.") from error
    _git(workspace, "add", "--all", "--", ".")
    staged_diff = _git(
        workspace,
        "diff",
        "--cached",
        "--no-ext-diff",
        "--unified=3",
        timeout=30,
    )
    if not staged_diff or len(staged_diff) > MAX_WORKSPACE_OUTPUT_CHARS:
        raise ContributorError(
            "The staged change is empty or too large to display safely. "
            "The workspace has not been published."
        )
    return staged_diff


def publish_draft_pull_request(
    workspace_info: dict[str, str],
    task: str,
    approved_diff: str,
) -> str:
    """Commit Buddy's staged patch, push its branch, and open a draft pull request."""
    workspace = Path(workspace_info["workspace"]).resolve()
    if not workspace.is_dir():
        raise ContributorError("The local contribution workspace no longer exists.")
    branch = workspace_info["branch"]
    if not branch.startswith("buddy/") or _git(workspace, "branch", "--show-current") != branch:
        raise ContributorError("Buddy will only publish its own active contribution branch.")
    remote = _canonical_remote(_git(workspace, "remote", "get-url", "origin"))
    expected_remote = (
        workspace_info["owner"].casefold(),
        workspace_info["repository"].casefold(),
    )
    if remote != expected_remote:
        raise ContributorError("The GitHub origin changed; Buddy will not push this branch.")

    status = _git(workspace, "status", "--porcelain")
    status_lines = status.splitlines()
    if any(line.startswith("??") for line in status_lines):
        raise ContributorError(
            "The workspace has untracked files. Review them before creating a pull request."
        )
    if any(line[:2][1] != " " for line in status_lines):
        raise ContributorError(
            "The workspace has unstaged changes. Review them and stage only the intended patch."
        )
    staged_diff = _git(
        workspace,
        "diff",
        "--cached",
        "--no-ext-diff",
        "--unified=3",
        timeout=30,
    )
    if not approved_diff or (staged_diff and staged_diff != approved_diff):
        raise ContributorError(
            "The staged changes differ from Buddy's displayed patch. "
            "Review the workspace before publishing."
        )
    if staged_diff:
        validate_patch(staged_diff)
    if any(line[:2].strip() for line in status_lines):
        title = re.sub(r"\s+", " ", task).strip()[:72]
        if not title:
            title = "Buddy contribution"
        _git(workspace, "commit", "-m", title, timeout=60)

    ahead = _git(
        workspace,
        "rev-list",
        "--count",
        f"origin/{workspace_info['base_branch']}..HEAD",
    )
    if not ahead.isdigit() or int(ahead) != 1:
        raise ContributorError("Buddy will only publish its single reviewed contribution commit.")
    committed_diff = _git(
        workspace,
        "show",
        "--format=",
        "--no-ext-diff",
        "--unified=3",
        "HEAD",
        timeout=30,
    )
    if committed_diff != approved_diff:
        raise ContributorError(
            "The commit differs from the patch you reviewed. Buddy will not push it."
        )

    _git(workspace, "push", "--set-upstream", "origin", branch, timeout=120)
    existing_url = _run(
        [
            "gh",
            "pr",
            "list",
            "--repo",
            f"{workspace_info['owner']}/{workspace_info['repository']}",
            "--head",
            branch,
            "--json",
            "url",
            "--jq",
            ".[0].url // empty",
        ],
        cwd=workspace,
        timeout=30,
    )
    if existing_url:
        return existing_url

    title = re.sub(r"\s+", " ", task).strip()[:72] or "Buddy contribution"
    body = (
        "## Summary\n"
        f"{task.strip()}\n\n"
        "## Review notes\n"
        "- Generated by Buddy (Security Sidekick); review every change before merging.\n"
        "- Buddy did not execute repository code or run its test suite.\n"
        "- GitHub Actions or other repository workflows may run for this pull request.\n\n"
        "🤖 Generated with Buddy Security Sidekick"
    )
    return _run(
        [
            "gh",
            "pr",
            "create",
            "--repo",
            f"{workspace_info['owner']}/{workspace_info['repository']}",
            "--base",
            workspace_info["base_branch"],
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
            "--draft",
        ],
        cwd=workspace,
        timeout=60,
    )
