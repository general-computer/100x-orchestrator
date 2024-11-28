import pytest
from app import app
import json
from pathlib import Path

@pytest.fixture
def client():
    """Create a test client for the Flask app."""
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

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

def test_create_agent_valid_data(client, monkeypatch):
    """Test create_agent route with valid data."""
    # Mock initialiseCodingAgent to return a test agent ID
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

def test_delete_agent_not_found(client):
    """Test delete_agent route with non-existent agent."""
    response = client.delete('/delete_agent/nonexistent-id')
    assert response.status_code == 404
    data = json.loads(response.data)
    assert data['success'] is False
