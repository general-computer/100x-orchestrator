import pytest
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from config import ConfigManager

def test_config_manager_initialization(tmp_path):
    """Test ConfigManager initialization with a config file."""
    config_file = tmp_path / "test_config.json"
    config = ConfigManager(str(config_file))
    assert config.config_file.exists()


def test_get_current_task(tmp_path):
    """Test getting current task from config."""
    config_file = tmp_path / "test_config.json"
    config = ConfigManager(str(config_file))
    # Default value when config is empty
    assert config.get_current_task() is None

def test_get_default_agents_per_task(tmp_path):
    """Test getting default agents per task from config."""
    config_file = tmp_path / "test_config.json"
    config = ConfigManager(str(config_file))
    # Default value when config is empty
    assert config.get_default_agents_per_task() == 1
