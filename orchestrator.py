import os, json, traceback, subprocess, sys, uuid
from pathlib import Path
import shutil
import tempfile
from time import sleep
from litellm import completion
from config import ConfigManager
import threading
import datetime
import queue
import io
import errno

# ANSI escape codes for color and formatting
class Colors:
    HEADER = '\033[95m'; OKBLUE = '\033[94m'; OKCYAN = '\033[96m'; OKGREEN = '\033[92m'
    WARNING = '\033[93m'; FAIL = '\033[91m'; ENDC = '\033[0m'; BOLD = '\033[1m'; UNDERLINE = '\033[4m'

# Configuration
MODEL_NAME = os.environ.get('LITELLM_MODEL', 'anthropic/claude-3-5-sonnet-20240620')
TASKS_FILE = Path("tasks/tasks.json")
config_manager = ConfigManager()
tools, available_functions = [], {}
MAX_TOOL_OUTPUT_LENGTH = 5000  # Adjust as needed
CHECK_INTERVAL = 30  # Reduced to 30 seconds for more frequent updates

# Global dictionary to store aider sessions
aider_sessions = {}

class AiderSession:
    def __init__(self, workspace_path, task):
        self.workspace_path = workspace_path
        self.task = task
        self.output_buffer = io.StringIO()
        self.process = None
        self.output_queue = queue.Queue()
        self._stop_event = threading.Event()

    def start(self):
        """Start the aider session"""
        try:
            # Create startupinfo to hide console window
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            
            # Start aider process
            cmd = f'aider --mini --message "{self.task}"'
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=self.workspace_path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                startupinfo=startupinfo,
                text=True,
                bufsize=1,
                universal_newlines=True
            )

            # Start output reading threads
            threading.Thread(target=self._read_output, args=(self.process.stdout,), daemon=True).start()
            threading.Thread(target=self._read_output, args=(self.process.stderr,), daemon=True).start()
            threading.Thread(target=self._process_output, daemon=True).start()

            return True
        except Exception as e:
            print(f"{Colors.FAIL}Failed to start aider session: {e}{Colors.ENDC}")
            return False

    def _read_output(self, pipe):
        """Read output from a pipe and put it in the queue"""
        try:
            for line in iter(pipe.readline, ''):
                if self._stop_event.is_set():
                    break
                self.output_queue.put(line)
        except Exception as e:
            print(f"{Colors.FAIL}Error reading output: {e}{Colors.ENDC}")
        finally:
            try:
                pipe.close()
            except Exception as e:
                print(f"{Colors.FAIL}Error closing pipe: {e}{Colors.ENDC}")

    def _process_output(self):
        """Process output from the queue and write to buffer"""
        while not self._stop_event.is_set():
            try:
                line = self.output_queue.get(timeout=0.1)
                self.output_buffer.write(line)
                # Update the output in tasks.json immediately
                self._update_output_in_tasks()
            except queue.Empty:
                continue
            except Exception as e:
                print(f"{Colors.FAIL}Error processing output: {e}{Colors.ENDC}")
                break

    def _update_output_in_tasks(self):
        """Update the output in tasks.json"""
        try:
            tasks_data = load_tasks()
            for agent_id, agent_data in tasks_data['agents'].items():
                if agent_data.get('workspace') == str(self.workspace_path):
                    agent_data['aider_output'] = self.get_output()
                    save_tasks(tasks_data)
                    break
        except Exception as e:
            print(f"{Colors.FAIL}Error updating output in tasks: {e}{Colors.ENDC}")

    def get_output(self):
        """Get the current output buffer contents"""
        try:
            return self.output_buffer.getvalue()
        except Exception as e:
            print(f"{Colors.FAIL}Error getting output: {e}{Colors.ENDC}")
            return ""

    def cleanup(self):
        """Clean up the aider session"""
        try:
            self._stop_event.set()
            if self.process:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
        except Exception as e:
            print(f"{Colors.FAIL}Error during cleanup: {e}{Colors.ENDC}")

def load_tasks():
    """Load tasks from tasks.json."""
    try:
        with open(TASKS_FILE, 'r') as f:
            data = json.load(f)
            if 'repository_url' not in data:
                data['repository_url'] = config_manager.get_repository_url()
            return data
    except FileNotFoundError:
        return {
            "tasks": [],
            "agents": {},
            "repository_url": config_manager.get_repository_url()
        }
    except json.JSONDecodeError:
        print(f"{Colors.FAIL}Error decoding tasks.json{Colors.ENDC}")
        return {
            "tasks": [],
            "agents": {},
            "repository_url": config_manager.get_repository_url()
        }

def save_tasks(tasks_data):
    """Save tasks to tasks.json."""
    try:
        # Create a copy of the data to avoid modifying the original
        data_to_save = {
            "tasks": tasks_data.get("tasks", []),
            "agents": {},
            "repository_url": tasks_data.get("repository_url", config_manager.get_repository_url())
        }
        
        # Copy agent data without the session object
        for agent_id, agent_data in tasks_data.get("agents", {}).items():
            data_to_save["agents"][agent_id] = {
                'workspace': agent_data.get('workspace'),
                'repo_path': agent_data.get('repo_path'),
                'task': agent_data.get('task'),
                'status': agent_data.get('status'),
                'created_at': agent_data.get('created_at'),
                'last_updated': agent_data.get('last_updated'),
                'aider_output': agent_data.get('aider_output', ''),
                'last_critique': agent_data.get('last_critique')
            }
        
        with open(TASKS_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=4)
    except Exception as e:
        print(f"{Colors.FAIL}Error saving tasks: {e}{Colors.ENDC}")

def delete_agent(agent_id):
    """Delete a specific agent and clean up its workspace."""
    try:
        tasks_data = load_tasks()
        
        # Find and remove the agent
        if agent_id in tasks_data['agents']:
            agent_data = tasks_data['agents'][agent_id]
            
            # Cleanup aider session if it exists
            if agent_id in aider_sessions:
                aider_sessions[agent_id].cleanup()
                del aider_sessions[agent_id]
            
            # Remove workspace directory if it exists
            workspace = agent_data.get('workspace')
            if workspace and os.path.exists(workspace):
                try:
                    shutil.rmtree(workspace)
                    print(f"{Colors.OKGREEN}Removed workspace for agent {agent_id}{Colors.ENDC}")
                except Exception as e:
                    print(f"{Colors.WARNING}Could not remove workspace: {e}{Colors.ENDC}")
            
            # Remove agent from tasks data
            del tasks_data['agents'][agent_id]
            save_tasks(tasks_data)
            
            print(f"{Colors.OKGREEN}Successfully deleted agent {agent_id}{Colors.ENDC}")
            return True
        else:
            print(f"{Colors.WARNING}No agent found with ID {agent_id}{Colors.ENDC}")
            return False
    except Exception as e:
        print(f"{Colors.FAIL}Error deleting agent: {e}{Colors.ENDC}")
        return False

def initialiseCodingAgent(repository_url: str = None, task_description: str = None, num_agents: int = None):
    """Initialise coding agents with configurable agent count."""
    # Use provided num_agents or get default from config
    num_agents = num_agents or config_manager.get_default_agents_per_task()
    
    # Validate input
    if not task_description:
        print(f"{Colors.FAIL}No task description provided{Colors.ENDC}")
        return None
    
    # Track created agent IDs
    created_agent_ids = []
    
    try:
        # Load tasks data to get repository URL
        tasks_data = load_tasks()
        if repository_url:
            tasks_data['repository_url'] = repository_url
            save_tasks(tasks_data)
        else:
            repository_url = tasks_data.get('repository_url')
        
        for _ in range(num_agents):
            # Generate unique agent ID
            agent_id = str(uuid.uuid4())
            
            # Create temporary workspace directory
            agent_workspace = Path(tempfile.mkdtemp(prefix=f"agent_{agent_id}_"))
            print(f"{Colors.OKGREEN}Created temporary workspace at: {agent_workspace}{Colors.ENDC}")
            
            # Create standard directory structure WITHIN the temporary workspace
            workspace_dirs = {
                "src": agent_workspace / "src",
                "tests": agent_workspace / "tests", 
                "docs": agent_workspace / "docs", 
                "config": agent_workspace / "config", 
                "repo": agent_workspace / "repo"
            }
            
            # Create all directories
            for dir_path in workspace_dirs.values():
                dir_path.mkdir(parents=True, exist_ok=True)
                
            # Create task file in agent workspace
            task_file = agent_workspace / "current_task.txt"
            task_file.write_text(task_description)
            
            # Store current directory
            original_dir = Path.cwd()
            
            try:
                # Clone repository into repo subdirectory
                os.chdir(workspace_dirs["repo"])
                if not repository_url:
                    print(f"{Colors.FAIL}No repository URL provided{Colors.ENDC}")
                    shutil.rmtree(agent_workspace)
                    continue
                
                if not cloneRepository(repository_url):
                    print(f"{Colors.FAIL}Failed to clone repository{Colors.ENDC}")
                    shutil.rmtree(agent_workspace)
                    continue
                
                # Get the cloned repository directory name
                repo_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and not d.startswith('.')]
                if not repo_dirs:
                    print(f"{Colors.FAIL}No repository directory found after cloning{Colors.ENDC}")
                    shutil.rmtree(agent_workspace)
                    continue
                
                repo_dir = repo_dirs[0]
                full_repo_path = workspace_dirs["repo"] / repo_dir
                
                # Change to the cloned repository directory
                os.chdir(full_repo_path)
                
                # Create and checkout new branch
                branch_name = f"agent-{agent_id[:8]}"
                try:
                    subprocess.check_call(f"git checkout -b {branch_name}", shell=True)
                except subprocess.CalledProcessError:
                    print(f"{Colors.FAIL}Failed to create new branch{Colors.ENDC}")
                    shutil.rmtree(agent_workspace)
                    continue

                # Initialize aider session
                aider_session = AiderSession(str(full_repo_path), task_description)
                if not aider_session.start():
                    print(f"{Colors.FAIL}Failed to start aider session{Colors.ENDC}")
                    shutil.rmtree(agent_workspace)
                    continue

                # Store session in global dictionary
                aider_sessions[agent_id] = aider_session

            finally:
                # Always return to original directory
                os.chdir(original_dir)
            
            # Update tasks.json with new agent
            tasks_data['agents'][agent_id] = {
                'workspace': str(agent_workspace),
                'repo_path': str(full_repo_path),
                'task': task_description,
                'status': 'pending',
                'created_at': datetime.datetime.now().isoformat(),
                'last_updated': datetime.datetime.now().isoformat(),
                'aider_output': ''  # Initialize empty output
            }
            save_tasks(tasks_data)
            
            print(f"{Colors.OKGREEN}Successfully initialized agent {agent_id}{Colors.ENDC}")
            created_agent_ids.append(agent_id)
        
        return created_agent_ids if created_agent_ids else None
        
    except Exception as e:
        print(f"{Colors.FAIL}Error initializing coding agents: {str(e)}{Colors.ENDC}")
        traceback.print_exc()
        return None

def cloneRepository(repository_url: str) -> bool:
    """Clone git repository using subprocess.check_call."""
    try:
        if not repository_url:
            print(f"{Colors.FAIL}No repository URL provided{Colors.ENDC}")
            return False
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
        
        # Use repo_path for file search
        repo_path = agent_data.get('repo_path')
        if not repo_path:
            print(f"{Colors.WARNING}No repo path found for agent {agent_id}{Colors.ENDC}")
            return None
            
        workspace = Path(repo_path)
        if not workspace.exists():
            print(f"{Colors.WARNING}Workspace path does not exist: {workspace}{Colors.ENDC}")
            return None
        
        src_files = list(workspace.glob('**/*.py'))  # Check Python files
        
        critique = {
            'files_created': len(src_files),
            'complexity': 'moderate',  # This would be a more sophisticated assessment
            'potential_improvements': []
        }
        
        # Update agent status based on critique
        agent_data['status'] = 'in_progress' if len(src_files) > 0 else 'pending'
        
        # Update aider output
        if agent_id in aider_sessions:
            agent_data['aider_output'] = aider_sessions[agent_id].get_output()
        
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
            for agent_id, agent_data in list(tasks_data['agents'].items()):
                print(f"{Colors.OKCYAN}Checking agent {agent_id}{Colors.ENDC}")
                
                # Critique progress
                critique = critique_agent_progress(agent_id)
                
                # Update prompt file in temporary workspace
                if agent_data.get('workspace'):
                    prompt_file = Path(agent_data['workspace']) / 'config' / 'prompt.txt'
                    prompt_file.parent.mkdir(parents=True, exist_ok=True)
                    prompt_file.write_text(json.dumps({
                        'task': agent_data.get('task', ''),
                        'status': agent_data.get('status', 'unknown'),
                        'last_critique': critique,
                        'aider_output': agent_data.get('aider_output', '')
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
