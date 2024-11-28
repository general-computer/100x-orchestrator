import pytest
import json
import os
import subprocess
from pathlib import Path
import threading
import queue
from unittest.mock import Mock, patch, MagicMock
from orchestrator import (
    AiderSession, 
    cloneRepository,
    load_tasks,
    save_tasks,
    critique_agent_progress,
    ConfigManager,
    main_loop
)

def test_aider_session_initialization(temp_workspace):
    """Test AiderSession initialization."""
    session = AiderSession(temp_workspace, "test task")
    assert session.workspace_path == temp_workspace
    assert session.task == "test task"
    assert session.process is None
    assert not session._stop_event.is_set()
    assert isinstance(session.output_queue, queue.Queue)
    assert session.session_id is not None

@patch('subprocess.Popen')
def test_aider_session_start(mock_popen, temp_workspace):
    """Test starting an aider session."""
    mock_process = Mock()
    mock_process.stdout = Mock()
    mock_process.stderr = Mock()
    mock_popen.return_value = mock_process
    
    session = AiderSession(temp_workspace, "test task")
    result = session.start()
    
    assert result is True
    assert session.process is not None
    mock_popen.assert_called_once()

def test_aider_session_cleanup(temp_workspace):
    """Test cleanup of aider session."""
    session = AiderSession(temp_workspace, "test task")
    session.process = Mock()
    
    session.cleanup()
    
    assert session._stop_event.is_set()
    session.process.terminate.assert_called_once()

def test_clone_repository(temp_workspace):
    """Test repository cloning functionality."""
    with patch('subprocess.check_call') as mock_check_call:
        repo_url = "https://github.com/test/repo"
        original_dir = os.getcwd()
        os.chdir(temp_workspace)
        try:
            result = cloneRepository(repo_url)
            assert result is True
            mock_check_call.assert_called_once_with(f"git clone {repo_url}", shell=True)
        finally:
            os.chdir(original_dir)

def test_clone_repository_failure(temp_workspace):
    """Test repository cloning failure."""
    with patch('subprocess.check_call', side_effect=subprocess.CalledProcessError(1, "git clone")):
        result = cloneRepository("invalid-url")
        assert result is False

def test_load_tasks_new_file():
    """Test loading tasks when file doesn't exist."""
    with patch('pathlib.Path.exists', return_value=False):
        result = load_tasks()
        assert isinstance(result, dict)
        assert 'tasks' in result
        assert 'agents' in result
        assert 'repository_url' in result

def test_load_tasks_existing_file(temp_workspace):
    """Test loading existing tasks file."""
    test_data = {
        "tasks": ["test task"],
        "agents": {},
        "repository_url": "https://github.com/test/repo"
    }
    tasks_file = temp_workspace / "tasks.json"
    with open(tasks_file, 'w') as f:
        json.dump(test_data, f)
    
    with patch('orchestrator.TASKS_FILE', tasks_file):
        result = load_tasks()
        assert result == test_data

def test_save_tasks(temp_workspace):
    """Test saving tasks to file."""
    tasks_file = temp_workspace / "tasks.json"
    test_data = {
        "tasks": ["test task"],
        "agents": {
            "agent-1": {
                "workspace": "test/workspace",
                "task": "test task",
                "status": "pending"
            }
        },
        "repository_url": "https://github.com/test/repo"
    }
    
    with patch('orchestrator.TASKS_FILE', tasks_file):
        save_tasks(test_data)
        assert tasks_file.exists()
        with open(tasks_file) as f:
            saved_data = json.load(f)
            assert saved_data["tasks"] == test_data["tasks"]
            assert "agent-1" in saved_data["agents"]

@patch('orchestrator.load_tasks')
@patch('orchestrator.save_tasks')
def test_critique_agent_progress(mock_save_tasks, mock_load_tasks, temp_workspace):
    """Test critiquing agent progress."""

@patch('orchestrator.load_tasks')
@patch('orchestrator.save_tasks')
@patch('orchestrator.critique_agent_progress')
@patch('orchestrator.sleep')
def test_main_loop_iteration(mock_sleep, mock_critique, mock_save, mock_load, temp_workspace):
    """Test a single iteration of the main loop with mocked dependencies."""
    # Setup mock data
    mock_tasks_data = {
        "agents": {
            "test-agent": {
                "workspace": str(temp_workspace),
                "task": "Test task", 
                "status": "pending"
            }
        }
    }
    mock_load.return_value = mock_tasks_data
    
    # Setup mock critique response
    mock_critique.return_value = {
        "files_created": 1,
        "complexity": "moderate",
        "potential_improvements": []
    }
    
    # Create a mock prompt file directory
    config_dir = temp_workspace / "config"
    config_dir.mkdir(exist_ok=True)
    
    # Run main_loop with a mock that raises KeyboardInterrupt after one iteration
    mock_sleep.side_effect = KeyboardInterrupt()
    
    # Execute main_loop and expect KeyboardInterrupt
    with pytest.raises(KeyboardInterrupt):
        main_loop()
    
    # Verify the mocks were called correctly
    mock_load.assert_called_once()
    mock_critique.assert_called_once_with("test-agent")
    mock_save.assert_called_once()
    mock_sleep.assert_called_once_with(30)  # CHECK_INTERVAL is 30
    test_data = {
        "agents": {
            "test-agent": {
                "repo_path": str(temp_workspace),
                "status": "pending"
            }
        }
    }
    mock_load_tasks.return_value = test_data
    
    # Create a test Python file
    (temp_workspace / "test.py").touch()
    
    result = critique_agent_progress("test-agent")
    
    assert result is not None
    assert "files_created" in result
    assert result["files_created"] == 1
    mock_save_tasks.assert_called_once()

