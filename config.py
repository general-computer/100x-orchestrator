import json
from pathlib import Path
from typing import List, Optional, Dict

class ConfigManager:
    def __init__(self, config_file: str = "config.json"):
        self.config_file = Path(config_file)
        self.config = self._load_config()

    def _load_config(self) -> Dict:
        """Load configuration from file or create default if not exists."""
        if self.config_file.exists():
            with open(self.config_file, 'r') as f:
                return json.load(f)
        else:
            default_config = {
                "repository_url": "",
                "tasks": [],
                "current_task_index": 0,
                "default_agents_per_task": 1  # New default agent count configuration
            }
            self._save_config(default_config)
            return default_config

    def _save_config(self, config: Dict) -> None:
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            json.dump(config, f, indent=2)

    def get_repository_url(self) -> str:
        """Get the configured repository URL."""
        return self.config.get("repository_url", "")

    def set_repository_url(self, url: str) -> None:
        """Set the repository URL."""
        self.config["repository_url"] = url
        self._save_config(self.config)

    def get_tasks(self) -> List[str]:
        """Get all tasks."""
        return self.config.get("tasks", [])

    def add_task(self, task: str) -> None:
        """Add a new task to the list."""
        if "tasks" not in self.config:
            self.config["tasks"] = []
        self.config["tasks"].append(task)
        self._save_config(self.config)

    def get_current_task(self) -> Optional[str]:
        """Get the current task."""
        tasks = self.config.get("tasks", [])
        current_index = self.config.get("current_task_index", 0)
        
        if not tasks or current_index >= len(tasks):
            return None
            
        return tasks[current_index]

    def advance_task(self) -> Optional[str]:
        """Move to the next task and return it."""
        self.config["current_task_index"] = self.config.get("current_task_index", 0) + 1
        self._save_config(self.config)
        return self.get_current_task()

    def reset_task_index(self) -> None:
        """Reset the task index to 0."""
        self.config["current_task_index"] = 0
        self._save_config(self.config)

    def get_default_agents_per_task(self) -> int:
        """Get the default number of agents per task."""
        return self.config.get("default_agents_per_task", 1)

    def set_default_agents_per_task(self, num_agents: int) -> None:
        """Set the default number of agents per task."""
        if num_agents < 1:
            raise ValueError("Number of agents must be at least 1")
        
        self.config["default_agents_per_task"] = num_agents
        self._save_config(self.config)
