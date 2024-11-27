import os, json, traceback, subprocess, sys, uuid
from pathlib import Path
import shutil
import tempfile
from time import sleep
from litellm import completion
from config import ConfigManager
import threading
import datetime
import pty
import io
import fcntl
import termios
import select

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
CHECK_INTERVAL = 300  # 5 minutes between agent checks

class AiderSession:
    def __init__(self, workspace_path, task):
        self.workspace_path = workspace_path
        self.task = task
        self.output_buffer = io.StringIO()
        self.process = None
        self.master_fd = None
        self.slave_fd = None

    def start(self):
        """Start the aider session in a pseudo-terminal"""
        try:
            # Create pseudo-terminal
            self.master_fd, self.slave_fd = pty.openpty()
            # Make the master non-blocking
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            # Start aider process
            cmd = f'aider --mini --message "{self.task}"'
            self.process = subprocess.Popen(
                cmd,
                shell=True,
                cwd=self.workspace_path,
                stdin=self.slave_fd,
                stdout=self.slave_fd,
                stderr=self.slave_fd,
                start_new_session=True
            )

            # Start output reading thread
            threading.Thread(target=self._read_output, daemon=True).start()
            return True
        except Exception as e:
            print(f"{Colors.FAIL}Failed to start aider session: {e}{Colors.ENDC}")
            return False

    def _read_output(self):
        """Read output from the pseudo-terminal"""
        try:
            while self.process.poll() is None:  # While process is running
                ready, _, _ = select.select([self.master_fd], [], [], 0.1)
                if ready:
                    try:
                        output = os.read(self.master_fd, 1024).decode()
                        self.output_buffer.write(output)
                    except (OSError, IOError) as e:
                        if e.errno != errno.EAGAIN:  # Ignore would-block errors
                            break
        except Exception as e:
            print(f"{Colors.FAIL}Error reading aider output: {e}{Colors.ENDC}")

    def get_output(self):
        """Get the current output buffer contents"""
        return self.output_buffer.getvalue()

    def cleanup(self):
        """Clean up the aider session"""
        if self.process:
            self.process.terminate()
            self.process.wait()
        if self.master_fd:
            os.close(self.master_fd)
        if self.slave_fd:
            os.close(self.slave_fd)

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

def delete_agent(agent_id):
    """Delete a specific agent and clean up its workspace."""
    try:
        tasks_data = load_tasks()
        
        # Find and remove the agent
        if agent_id in tasks_data['agents']:
            agent_data = tasks_data['agents'][agent_id]
            
            # Cleanup aider session if it exists
            if 'aider_session' in agent_data:
                agent_data['aider_session'].cleanup()
            
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
                repo_url = repository_url or config_manager.get_repository_url()
                if not cloneRepository(repo_url):
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

            finally:
                # Always return to original directory
                os.chdir(original_dir)
            
            # Update tasks.json with new agent
            tasks_data = load_tasks()
            tasks_data['agents'][agent_id] = {
                'workspace': str(agent_workspace),
                'repo_path': str(full_repo_path),
                'task': task_description,
                'status': 'pending',
                'created_at': datetime.datetime.now().isoformat(),
                'last_updated': datetime.datetime.now().isoformat(),
                'aider_output': '',  # Initialize empty output
                'aider_session': aider_session  # Store session object
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
        workspace = Path(agent_data.get('repo_path', ''))
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
        if 'aider_session' in agent_data:
            agent_data['aider_output'] = agent_data['aider_session'].get_output()
        
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
