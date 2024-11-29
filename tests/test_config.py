import pytest
import sys
import json
from pathlib import Path

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator import load_tasks, save_tasks

def test_load_tasks_new_file(tmp_path, monkeypatch):
    """Test loading tasks when config file doesn't exist."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("orchestrator.CONFIG_FILE", config_path)
    
    tasks_data = load_tasks()
    assert isinstance(tasks_data, dict)
    assert "tasks" in tasks_data
    assert "agents" in tasks_data
    assert "repository_url" in tasks_data

def test_save_and_load_tasks(tmp_path, monkeypatch):
    """Test saving and loading tasks configuration."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("orchestrator.CONFIG_FILE", config_path)
    
    test_data = {
        "tasks": ["test task 1", "test task 2"],
        "agents": {
            "test-agent-1": {
                "workspace": str(tmp_path / "agent1"),
                "repo_path": str(tmp_path / "agent1/repo"),
                "task": "test task 1",
                "status": "pending"
            }
        },
        "repository_url": "https://github.com/test/repo"
    }
    
    save_tasks(test_data)
    loaded_data = load_tasks()
    
    assert loaded_data["tasks"] == test_data["tasks"]
    assert loaded_data["repository_url"] == test_data["repository_url"]
    assert "test-agent-1" in loaded_data["agents"]

def test_load_tasks_invalid_json(tmp_path, monkeypatch):
    """Test loading tasks with invalid JSON file."""
    config_path = tmp_path / "config.json"
    monkeypatch.setattr("orchestrator.CONFIG_FILE", config_path)
    
    # Write invalid JSON
    config_path.write_text("{invalid json")
    
    tasks_data = load_tasks()
    assert isinstance(tasks_data, dict)
    assert "tasks" in tasks_data
    assert "agents" in tasks_data
    assert tasks_data["tasks"] == []
