import pytest
import sys
from pathlib import Path

# Add the project root to Python path
sys.path.append(str(Path(__file__).parent.parent))

from orchestrator import AiderSession, cloneRepository

def test_aider_session_initialization(tmp_path):
    """Test AiderSession initialization."""
    workspace = str(tmp_path / "test_workspace")
    session = AiderSession(workspace, "test task")
    assert session.workspace_path == workspace
    assert session.task == "test task"
    assert session.process is None
    assert not session._stop_event.is_set()

@pytest.mark.skip(reason="Requires network access and git installation")
def test_clone_repository():
    """Test repository cloning functionality."""
    # Skip this test as it requires network access
    pass
