import pytest
from buddy_contributor import ContributorError
from buddy_agent import generate_task_patch

def test_generate_task_patch_security_policy():
    patch = generate_task_patch("security-policy", [])
    assert "diff --git a/SECURITY.md b/SECURITY.md" in patch
    assert "+# Security Policy" in patch

def test_generate_task_patch_dependency_check():
    patch = generate_task_patch("dependency-check", [])
    assert "diff --git a/.github/dependabot.yml b/.github/dependabot.yml" in patch
    assert "+version: 2" in patch

def test_generate_task_patch_invalid_task():
    with pytest.raises(ContributorError, match="not supported"):
        generate_task_patch("non-existent-task", [])
