import pytest
from config import ConfigManager
import json
from pathlib import Path

def test_config_manager_initialization(temp_config_file):
    """Test ConfigManager initialization with a config file."""
    config = ConfigManager(temp_config_file)
    assert config.config_file.exists()

def test_config_manager_default_creation():
    """Test ConfigManager creates default config if file doesn't exist."""
    config = ConfigManager("nonexistent.json")
    assert config.get_repository_url() == ""
    assert config.get_tasks() == []
    assert config.get_current_task() is None
    Path("nonexistent.json").unlink()

def test_get_repository_url(temp_config_file):
    """Test getting repository URL from config."""
    config = ConfigManager(temp_config_file)
    assert config.get_repository_url() == "https://github.com/test/repo"

def test_set_repository_url(temp_config_file):
    """Test setting repository URL."""
    config = ConfigManager(temp_config_file)
    new_url = "https://github.com/new/repo"
    config.set_repository_url(new_url)
    assert config.get_repository_url() == new_url

def test_get_tasks(temp_config_file):
    """Test getting tasks list."""
    config = ConfigManager(temp_config_file)
    assert config.get_tasks() == ["test task"]

def test_add_task(temp_config_file):
    """Test adding a new task."""
    config = ConfigManager(temp_config_file)
    config.add_task("new task")
    assert "new task" in config.get_tasks()

def test_get_current_task(temp_config_file):
    """Test getting current task from config."""
    config = ConfigManager(temp_config_file)
    assert config.get_current_task() == "test task"

def test_advance_task(temp_config_file):
    """Test advancing to next task."""
    config = ConfigManager(temp_config_file)
    config.add_task("second task")
    advanced_task = config.advance_task()
    assert advanced_task == "second task"
    assert config.get_current_task() == "second task"

def test_reset_task_index(temp_config_file):
    """Test resetting task index."""
    config = ConfigManager(temp_config_file)
    config.add_task("second task")
    config.advance_task()
    config.reset_task_index()
    assert config.get_current_task() == "test task"

def test_get_default_agents_per_task(temp_config_file):
    """Test getting default agents per task."""
    config = ConfigManager(temp_config_file)
    assert config.get_default_agents_per_task() == 2

def test_set_default_agents_per_task(temp_config_file):
    """Test setting default agents per task."""
    config = ConfigManager(temp_config_file)
    config.set_default_agents_per_task(3)
    assert config.get_default_agents_per_task() == 3

def test_set_default_agents_invalid_value(temp_config_file):
    """Test setting invalid number of default agents."""
    config = ConfigManager(temp_config_file)
    with pytest.raises(ValueError):
        config.set_default_agents_per_task(0)
