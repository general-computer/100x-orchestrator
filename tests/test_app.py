import pytest
from app import app
import json
from pathlib import Path
import tempfile
import os

@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

@pytest.fixture
def mock_tasks_file():
    """Create a temporary tasks.json file for testing."""
    tasks_dir = Path('tasks')
    tasks_dir.mkdir(exist_ok=True)
    
    test_data = {
        "tasks": ["Test task 1", "Test task 2"],
        "agents": {
            "test-agent-1": {
                "task": "Test task 1",
                "workspace": "workspaces/test-agent-1",
                "status": "pending"
            }
        },
        "repository_url": "https://github.com/test/repo"
    }
    
    tasks_file = tasks_dir / 'tasks.json'
    with open(tasks_file, 'w') as f:
        json.dump(test_data, f)
    
    yield tasks_file
    
    # Cleanup
    if tasks_file.exists():
        tasks_file.unlink()

def test_index_route(client):
    """Test the index route returns successfully."""
    response = client.get('/')
    assert response.status_code == 200

def test_create_agent_missing_data(client):
    """Test create_agent route with missing data."""
    response = client.post('/create_agent', 
                         json={})
    assert response.status_code == 400
    data = json.loads(response.data)
    assert 'error' in data
    assert 'Repository URL and tasks are required' in data['error']

def test_create_agent_valid_data(client, monkeypatch, mock_tasks_file):
    """Test create_agent route with valid data."""
    def mock_init(*args, **kwargs):
        return ['test-agent-id']
    monkeypatch.setattr('app.initialiseCodingAgent', mock_init)
    
    test_data = {
        'repo_url': 'https://github.com/test/repo',
        'tasks': ['Test task'],
        'num_agents': 1
    }
    response = client.post('/create_agent',
                         json=test_data)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True
    assert 'test-agent-id' in data['agent_ids']

def test_create_agent_with_string_task(client, monkeypatch, mock_tasks_file):
    """Test create_agent route with string task instead of list."""
    def mock_init(*args, **kwargs):
        return ['test-agent-id']
    monkeypatch.setattr('app.initialiseCodingAgent', mock_init)
    
    test_data = {
        'repo_url': 'https://github.com/test/repo',
        'tasks': 'Single task',
        'num_agents': 1
    }
    response = client.post('/create_agent',
                         json=test_data)
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

def test_delete_agent_not_found(client):
    """Test delete_agent route with non-existent agent."""
    response = client.delete('/delete_agent/nonexistent-id')
    assert response.status_code == 404
    data = json.loads(response.data)
    assert data['success'] is False

def test_delete_agent_success(client, mock_tasks_file, monkeypatch):
    """Test successful agent deletion."""
    def mock_delete(*args):
        return True
    monkeypatch.setattr('app.delete_agent', mock_delete)
    
    response = client.delete('/delete_agent/test-agent-1')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data['success'] is True

def test_serve_tasks_json(client, mock_tasks_file):
    """Test serving tasks.json file."""
    response = client.get('/tasks/tasks.json')
    assert response.status_code == 200
    data = json.loads(response.data)
    assert 'tasks' in data
    assert 'agents' in data
    assert data['repository_url'] == 'https://github.com/test/repo'

def test_agent_view(client, mock_tasks_file):
    """Test the agent view route."""
    # Create a temporary workspace structure for testing
    workspace_path = Path('workspaces/test-agent-1')
    workspace_path.mkdir(parents=True, exist_ok=True)
    config_path = workspace_path / 'config'
    config_path.mkdir(exist_ok=True)
    
    # Create a test prompt.txt
    prompt_data = {
        'task': 'Test task 1',
        'status': 'pending',
        'last_critique': None
    }
    with open(config_path / 'prompt.txt', 'w') as f:
        json.dump(prompt_data, f)
    
    try:
        response = client.get('/agents')
        assert response.status_code == 200
        assert b'test-agent-1' in response.data
    finally:
        # Cleanup
        import shutil
        if workspace_path.exists():
            shutil.rmtree(workspace_path)
