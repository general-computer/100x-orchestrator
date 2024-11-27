import os, json, traceback, subprocess, sys, uuid
from pathlib import Path
import shutil
from time import sleep
from litellm import completion
from config import ConfigManager
import threading
import datetime

# ANSI escape codes for color and formatting
class Colors:
    HEADER = '\033[95m'; OKBLUE = '\033[94m'; OKCYAN = '\033[96m'; OKGREEN = '\033[92m'
    WARNING = '\033[93m'; FAIL = '\033[91m'; ENDC = '\033[0m'; BOLD = '\033[1m'; UNDERLINE = '\033[4m'

# Configuration
MODEL_NAME = os.environ.get('LITELLM_MODEL', 'anthropic/claude-3-5-sonnet-20240620')
WORKSPACE_DIR = Path("workspaces")
TASKS_FILE = Path("tasks/tasks.json")
config_manager = ConfigManager()
tools, available_functions = [], {}
MAX_TOOL_OUTPUT_LENGTH = 5000  # Adjust as needed
CHECK_INTERVAL = 300  # 5 minutes between agent checks

def load_tasks():
    """Load tasks from tasks.json."""
    try:
        with open(TASKS_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {"tasks": [], "agents": {}}
    except json.JSONDecodeError:
        print(f"{Colors.FAIL}Error decoding tasks.json{Colors.ENDC}")
        return {"tasks": [], "agents": {}}

def save_tasks(tasks_data):
    """Save tasks to tasks.json."""
    try:
        with open(TASKS_FILE, 'w') as f:
            json.dump(tasks_data, f, indent=4)
    except Exception as e:
        print(f"{Colors.FAIL}Error saving tasks: {e}{Colors.ENDC}")

def initialiseCodingAgent(repository_url: str = None, task_description: str = None):
    """Initialise the coding agent with workspace setup and repository management."""
    try:
        # Generate unique agent ID
        agent_id = str(uuid.uuid4())
        
        # Create workspace directories
        workspace_base = WORKSPACE_DIR
        agent_workspace = workspace_base / f"agent_{agent_id}_1"
        
        # Check if workspace already exists
        if agent_workspace.exists():
            print(f"{Colors.WARNING}Workspace already exists, cleaning up...{Colors.ENDC}")
            shutil.rmtree(agent_workspace)
        
        # Create standard directory structure
        for dir_name in ["src", "tests", "docs", "config"]:
            (agent_workspace / dir_name).mkdir(parents=True, exist_ok=True)
            
        # Validate task description
        if not task_description:
            print(f"{Colors.FAIL}No task description provided{Colors.ENDC}")
            return None
            
        # Create task file in agent workspace
        task_file = agent_workspace / "current_task.txt"
        task_file.write_text(task_description)
        
        # Store current directory
        original_dir = Path.cwd()
        
        try:
            # Clone repository and create new branch
            os.chdir(agent_workspace)
            repo_url = repository_url or os.environ.get('REPOSITORY_URL')
            if not cloneRepository(repo_url):
                print(f"{Colors.FAIL}Failed to clone repository{Colors.ENDC}")
                return None
            
            # Create and checkout new branch
            branch_name = f"agent-{agent_id[:8]}"
            try:
                subprocess.check_call(f"git checkout -b {branch_name}", shell=True)
            except subprocess.CalledProcessError:
                print(f"{Colors.FAIL}Failed to create new branch{Colors.ENDC}")
                return None
        finally:
            # Always return to original directory
            os.chdir(original_dir)
        
        # Update tasks.json with new agent
        tasks_data = load_tasks()
        tasks_data['agents'][agent_id] = {
            'workspace': str(agent_workspace),
            'task': task_description,
            'status': 'pending',
            'created_at': datetime.datetime.now().isoformat(),
            'last_updated': datetime.datetime.now().isoformat()
        }
        save_tasks(tasks_data)
        
        print(f"{Colors.OKGREEN}Successfully initialized agent {agent_id}{Colors.ENDC}")
        return agent_id
        
    except Exception as e:
        print(f"{Colors.FAIL}Error initializing coding agent: {str(e)}{Colors.ENDC}")
        traceback.print_exc()
        return None

def cloneRepository(repository_url: str) -> bool:
    """Clone git repository using subprocess.check_call."""
    try:
        subprocess.check_call(f"git clone {repository_url}", shell=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"{Colors.FAIL}Git clone failed with exit code {e.returncode}{Colors.ENDC}")
        return False

def critique_agent_progress(agent_id):
    """Critique the progress of a specific agent."""
    try:
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            print(f"{Colors.FAIL}No agent found with ID {agent_id}{Colors.ENDC}")
            return None
        
        # Simulate progress critique (replace with actual AI-based critique)
        workspace = Path(agent_data['workspace'])
        src_files = list(workspace.glob('**/*.py'))  # Check Python files
        
        critique = {
            'files_created': len(src_files),
            'complexity': 'moderate',  # This would be a more sophisticated assessment
            'potential_improvements': []
        }
        
        # Update agent status based on critique
        if len(src_files) > 0:
            agent_data['status'] = 'in_progress'
        else:
            agent_data['status'] = 'pending'
        
        agent_data['last_critique'] = critique
        agent_data['last_updated'] = datetime.datetime.now().isoformat()
        
        save_tasks(tasks_data)
        return critique
    
    except Exception as e:
        print(f"{Colors.FAIL}Error critiquing agent progress: {e}{Colors.ENDC}")
        return None

def main_loop():
    """Main orchestration loop to manage agents."""
    while True:
        try:
            # Load current tasks and agents
            tasks_data = load_tasks()
            
            # Check each agent's progress
            for agent_id, agent_data in tasks_data['agents'].items():
                print(f"{Colors.OKCYAN}Checking agent {agent_id}{Colors.ENDC}")
                
                # Critique progress
                critique = critique_agent_progress(agent_id)
                
                # Update prompt file (simulated)
                prompt_file = Path(agent_data['workspace']) / 'config' / 'prompt.txt'
                prompt_file.parent.mkdir(parents=True, exist_ok=True)
                prompt_file.write_text(json.dumps({
                    'task': agent_data['task'],
                    'status': agent_data['status'],
                    'last_critique': critique
                }, indent=4))
            
            # Save updated tasks
            save_tasks(tasks_data)
            
            # Wait before next check
            sleep(CHECK_INTERVAL)
        
        except Exception as e:
            print(f"{Colors.FAIL}Error in main loop: {e}{Colors.ENDC}")
            traceback.print_exc()
            sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main_loop()
