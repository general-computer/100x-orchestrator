# 100x-orchestrator

A sophisticated orchestration system that manages multiple AI coding agents working on software development tasks. The system leverages Aider (an AI coding assistant) to handle coding tasks and provides a web interface for monitoring and managing these agents.

## Features

- **Multi-Agent Task Handling**: Deploy multiple AI agents to work on coding tasks simultaneously
- **Git Integration**: Automatic repository cloning and branch management
- **Real-Time Progress Monitoring**: Track agent progress and status through a web interface
- **Workspace Isolation**: Each agent works in an isolated workspace to prevent conflicts
- **Configuration Management**: Flexible configuration system for repository URLs and task management
- **Web-Based Control Interface**: User-friendly web interface for agent creation and management
- **Automated Code Critiquing**: Built-in system for evaluating agent progress and code quality
- **Session Management**: Robust handling of agent sessions and outputs

## System Architecture

### 1. Orchestrator (`orchestrator.py`)
- Core component managing AI coding agents
- Handles workspace creation and git repository management
- Monitors agent progress and provides critiques
- Maintains agent sessions and outputs
- Integrates with Aider for code generation

### 2. Configuration Manager (`config.py`)
- Manages system configuration
- Handles repository URLs and task tracking
- Controls agent count per task
- Persists configuration in JSON format

### 3. Web Interface (`app.py`)
- Flask-based web application
- Agent creation and management interface
- Real-time status and progress display
- Task assignment and monitoring
- Agent deletion and cleanup functionality

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/100x-orchestrator.git
cd 100x-orchestrator
```

2. Create and activate a virtual environment:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Configuration

1. Create a `config.json` file in the root directory:
```json
{
  "repository_url": "",
  "tasks": [],
  "current_task_index": 0,
  "default_agents_per_task": 1
}
```

2. Set up your environment variables:
```bash
export LITELLM_MODEL=anthropic/claude-3-5-sonnet-20240620  # Or your preferred model
```

## Usage

1. Start the web server:
```bash
python app.py
```

2. Access the web interface at `http://localhost:5000`

3. Create new agents:
   - Provide a repository URL
   - Define tasks
   - Set the number of agents per task
   - Click "Create Agent"

4. Monitor progress:
   - View agent status in the web interface
   - Check agent outputs and critiques
   - Manage agent lifecycle

## Project Structure

```
100x-orchestrator/
├── app.py              # Web interface
├── orchestrator.py     # Core orchestration logic
├── config.py          # Configuration management
├── requirements.txt   # Project dependencies
├── tasks/            # Task storage
├── templates/        # Web interface templates
└── workspaces/       # Agent workspaces
```

## Technical Stack

- Python
- Flask
- Aider
- Git
- JSON for configuration
- Threading for concurrent operations

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## License

[MIT License](LICENSE)
