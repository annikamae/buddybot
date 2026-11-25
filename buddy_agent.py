"""Task-specific agentic contributions for Buddy."""

from buddy_contributor import ContributorError

def get_contribution_tasks():
    """Return supported automated contribution tasks."""
    return {
        "security-policy": {
            "title": "Add/Update SECURITY.md",
            "description": "Adds or updates a standard SECURITY.md policy file to the repository root.",
            "content": """# Security Policy

## Reporting Vulnerabilities

Please report security vulnerabilities to the maintainers of this repository."""
        },
        "dependency-check": {
            "title": "Add Dependabot configuration",
            "description": "Adds a basic .github/dependabot.yml configuration file.",
            "content": """version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
  - package-ecosystem: "npm"
    directory: "/"
    schedule:
      interval: "weekly"
"""
        }
    }

def generate_task_patch(task_key: str, repository_files: list[str]) -> str:
    """Generate a patch for a specific predefined task."""
    tasks = get_contribution_tasks()
    if task_key not in tasks:
        raise ContributorError(f"Task '{task_key}' is not supported.")

    # Simple logic to determine where to add the file
    if task_key == "security-policy":
        return (
            "diff --git a/SECURITY.md b/SECURITY.md\n"
            "new file mode 100644\n"
            "index 0000000..e69de29\n"
            "--- /dev/null\n"
            "+++ b/SECURITY.md\n"
            "@@ -0,0 +1,5 @@\n"
            "+# Security Policy\n"
            "+\n"
            "+## Reporting Vulnerabilities\n"
            "+\n"
            "+Please report security vulnerabilities to the maintainers of this repository."
        )

    if task_key == "dependency-check":
        return (
            "diff --git a/.github/dependabot.yml b/.github/dependabot.yml\n"
            "new file mode 100644\n"
            "index 0000000..8b33230\n"
            "--- /dev/null\n"
            "+++ b/.github/dependabot.yml\n"
            "@@ -0,0 +1,10 @@\n"
            "+version: 2\n"
            "+updates:\n"
            "+  - package-ecosystem: \"pip\"\n"
            "+    directory: \"/\"\n"
            "+    schedule:\n"
            "+      interval: \"weekly\"\n"
            "+  - package-ecosystem: \"npm\"\n"
            "+    directory: \"/\"\n"
            "+    schedule:\n"
            "+      interval: \"weekly\""
        )
