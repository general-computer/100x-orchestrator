import pytest
from orchestrator import AiderSession, cloneRepository

def test_aider_session_initialization(temp_workspace):
    """Test AiderSession initialization."""
    session = AiderSession(temp_workspace, "test task")
    assert session.workspace_path == temp_workspace
    assert session.task == "test task"
    assert session.process is None
    assert not session._stop_event.is_set()

def test_clone_repository(temp_workspace):
    """Test repository cloning functionality."""
    # Using a public test repo that's guaranteed to exist
    repo_name = "pytest-example"
    repo_url = "https://github.com/pytest-dev/pytest"
    # Change to temp workspace before cloning
    import os
    original_dir = os.getcwd()
    os.chdir(temp_workspace)
    try:
        result = cloneRepository(repo_url)
        assert result is True
    finally:
        os.chdir(original_dir)
