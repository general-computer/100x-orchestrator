import pytest
import sys
import os
from pathlib import Path
import threading
import queue
import json

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator import (
    AiderSession, 
    cloneRepository,
    normalize_path,
    validate_agent_paths
)

class TestAiderSession:
    """Test suite for AiderSession class."""
    
    def test_initialization(self, temp_workspace):
        """Test proper initialization of AiderSession."""
        session = AiderSession(str(temp_workspace), "Implement new feature")
        
        assert session.workspace_path == str(temp_workspace)
        assert session.task == "Implement new feature"
        assert session.process is None
        assert isinstance(session.output_queue, queue.Queue)
        assert isinstance(session._stop_event, threading.Event)
        assert len(session.session_id) == 8  # UUID first 8 chars
        
    def test_start_and_cleanup(self, temp_workspace, mock_aider_process):
        """Test session start and cleanup procedures."""
        mock_process, mock_popen = mock_aider_process
        session = AiderSession(str(temp_workspace), "Debug existing code")
        
        # Test start
        session.start()
        assert session.process is not None
        mock_popen.assert_called_once()
        
        # Test cleanup
        session.cleanup()
        assert session._stop_event.is_set()
        mock_process.terminate.assert_called_once()
    
    def test_output_handling(self, temp_workspace, mock_aider_process):
        """Test output capture and processing."""
        session = AiderSession(str(temp_workspace), "Code review")
        session.start()
        
        # Simulate some output
        session.output_queue.put("Working on task...")
        session.output_queue.put("Found issue in main.py")
        
        output = session.get_output()
        assert "Working on task..." in output
        assert "Found issue in main.py" in output

class TestRepositoryManagement:
    """Test suite for repository management functions."""
    
    def test_clone_repository(self, temp_workspace, mock_git):
        """Test repository cloning functionality."""
        repo_url = "https://github.com/test/repo.git"
        success = cloneRepository(repo_url)
        
        assert success
        mock_git.clone_from.assert_called_once_with(
            repo_url,
            str(temp_workspace),
            depth=1
        )
    
    def test_normalize_path(self):
        """Test path normalization function."""
        test_paths = {
            "/path/to/somewhere": "/path/to/somewhere",
            "relative/path": os.path.abspath("relative/path"),
            "~/home/dir": os.path.expanduser("~/home/dir"),
        }
        
        for input_path, expected in test_paths.items():
            assert normalize_path(input_path) == expected
    
    def test_validate_agent_paths(self, temp_workspace):
        """Test agent path validation."""
        agent_id = "agent123"
        
        # Create test directory structure
        agent_dir = temp_workspace / f"agent_{agent_id}"
        agent_dir.mkdir()
        (agent_dir / "workspace").mkdir()
        
        # Test validation
        is_valid = validate_agent_paths(agent_id, str(temp_workspace))
        assert is_valid
        
        # Test invalid path
        is_valid = validate_agent_paths("invalid_agent", str(temp_workspace))
        assert not is_valid
