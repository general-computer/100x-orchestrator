import pytest
from pathlib import Path
import tempfile
import json
import os
import shutil
from unittest.mock import MagicMock

@pytest.fixture
def test_config():
    """Fixture that provides test configuration data."""
    return {
        "repository_url": "https://github.com/test/repo",
        "current_task": "test task",
        "default_agents_per_task": 2,
        "api_key": "test-key",
        "model": "gpt-4"
    }

@pytest.fixture
def temp_config_file(test_config):
    """Fixture that creates a temporary config file with test configuration."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        json.dump(test_config, f, indent=2)
        config_path = f.name
    
    yield config_path
    # Cleanup
    if os.path.exists(config_path):
        Path(config_path).unlink()

@pytest.fixture
def temp_workspace():
    """
    Fixture that creates a temporary workspace directory with a git-like structure.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        
        # Create basic directory structure
        (workspace / ".git").mkdir()
        (workspace / "src").mkdir()
        (workspace / "tests").mkdir()
        
        # Create some dummy files
        (workspace / "README.md").write_text("# Test Repository")
        (workspace / "requirements.txt").write_text("pytest\nflask")
        
        yield workspace

@pytest.fixture
def mock_aider_process(mocker):
    """Fixture that provides a mock for subprocess operations."""
    mock_process = MagicMock()
    mock_process.poll.return_value = None  # Process running
    mock_process.stdout.readline.return_value = b"AI Assistant: Ready\n"
    
    mock_popen = mocker.patch('subprocess.Popen', return_value=mock_process)
    return mock_process, mock_popen

@pytest.fixture
def mock_git(mocker):
    """Fixture that provides a mock for git operations."""
    mock_repo = MagicMock()
    mock_repo.clone_from.return_value = True
    mocker.patch('git.Repo.clone_from', return_value=mock_repo)
    return mock_repo
