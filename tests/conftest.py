import pytest
from pathlib import Path
import tempfile
import json
import os

@pytest.fixture
def temp_config_file():
    """Fixture that creates a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        test_config = {
            "repository_url": "https://github.com/test/repo",
            "tasks": ["test task"],
            "current_task_index": 0,
            "default_agents_per_task": 2
        }
        json.dump(test_config, f)
        config_path = f.name
    
    yield config_path
    Path(config_path).unlink()  # Cleanup after test

@pytest.fixture
def temp_workspace():
    """Fixture that creates a temporary workspace directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)
        # Create standard workspace structure
        (path / "config").mkdir()
        (path / "src").mkdir()
        (path / "tests").mkdir()
        yield path

@pytest.fixture
def mock_tasks_file(temp_workspace):
    """Fixture that creates a temporary tasks.json file."""
    tasks_file = temp_workspace / "tasks.json"
    test_data = {
        "tasks": ["Test task"],
        "agents": {
            "test-agent": {
                "workspace": str(temp_workspace),
                "task": "Test task",
                "status": "pending"
            }
        },
        "repository_url": "https://github.com/test/repo"
    }
    
    with open(tasks_file, 'w') as f:
        json.dump(test_data, f)
    
    yield tasks_file
