import pytest
from config import ConfigManager

def test_config_manager_initialization(temp_config_file):
    """Test ConfigManager initialization with a config file."""
    config = ConfigManager(temp_config_file)
    assert config.config_file.exists()

def test_get_repository_url(temp_config_file):
    """Test getting repository URL from config."""
    config = ConfigManager(temp_config_file)
    assert config.get_repository_url() == "https://github.com/test/repo"

def test_get_current_task(temp_config_file):
    """Test getting current task from config."""
    config = ConfigManager(temp_config_file)
    assert config.get_current_task() == "test task"

def test_get_default_agents_per_task(temp_config_file):
    """Test getting default agents per task from config."""
    config = ConfigManager(temp_config_file)
    assert config.get_default_agents_per_task() == 2
