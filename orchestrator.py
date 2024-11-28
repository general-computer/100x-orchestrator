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
import logging

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('aider_debug.log'),
        logging.StreamHandler()
    ]
)

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
        self.session_id = str(uuid.uuid4())[:8]  # For logging
        logging.info(f"[Session {self.session_id}] Initialized with workspace: {workspace_path}")

    def start(self):
        """Start the aider session"""
        try:
            logging.info(f"[Session {self.session_id}] Starting aider session")
            
            # Start aider process
            cmd = f'aider --mini --message "{self.task}"'
            logging.info(f"[Session {self.session_id}] Executing command: {cmd}")
            
            # Platform-specific Popen arguments
            popen_kwargs = {
                'shell': True,
                'cwd': self.workspace_path,
                'stdout': subprocess.PIPE,
                'stderr': subprocess.PIPE,
                'text': True,
                'bufsize': 1,
                'universal_newlines': True
            }
            
            # Add startupinfo on Windows only
            if os.name == 'nt':
                startupinfo = subprocess.STARTUPINFO()
                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                popen_kwargs['startupinfo'] = startupinfo
            
            self.process = subprocess.Popen(cmd, **popen_kwargs)
            
            logging.info(f"[Session {self.session_id}] Process started with PID: {self.process.pid}")

            # Start output reading threads
            threading.Thread(target=self._read_output, args=(self.process.stdout, "stdout"), daemon=True).start()
            threading.Thread(target=self._read_output, args=(self.process.stderr, "stderr"), daemon=True).start()
            threading.Thread(target=self._process_output, daemon=True).start()

            return True
        except Exception as e:
            logging.error(f"[Session {self.session_id}] Failed to start aider session: {e}", exc_info=True)
            return False

    def _read_output(self, pipe, pipe_name):
        """Read output from a pipe and put it in the queue"""
        try:
            logging.info(f"[Session {self.session_id}] Started reading from {pipe_name}")
            for line in iter(pipe.readline, ''):
                if self._stop_event.is_set():
                    break
                logging.debug(f"[Session {self.session_id}] {pipe_name} received: {line.strip()}")
                self.output_queue.put(line)
        except Exception as e:
            logging.error(f"[Session {self.session_id}] Error reading from {pipe_name}: {e}", exc_info=True)
        finally:
            try:
                pipe.close()
                logging.info(f"[Session {self.session_id}] Closed {pipe_name} pipe")
            except Exception as e:
                logging.error(f"[Session {self.session_id}] Error closing {pipe_name} pipe: {e}", exc_info=True)

    def _process_output(self):
        """Process output from the queue and write to buffer"""
        logging.info(f"[Session {self.session_id}] Started output processing thread")
        while not self._stop_event.is_set():
            try:
                line = self.output_queue.get(timeout=0.1)
                current_pos = self.output_buffer.tell()
                self.output_buffer.write(line)
                logging.debug(f"[Session {self.session_id}] Processed output line: {line.strip()}")
                
                # Log buffer position changes
                new_pos = self.output_buffer.tell()
                logging.debug(f"[Session {self.session_id}] Buffer position moved from {current_pos} to {new_pos}")
                
                # Update the output in tasks.json immediately
                self._update_output_in_tasks()
            except queue.Empty:
                continue
            except Exception as e:
                logging.error(f"[Session {self.session_id}] Error processing output: {e}", exc_info=True)
                break

    def _update_output_in_tasks(self):
        """Update the output in tasks.json"""
        try:
            tasks_data = load_tasks()
            updated = False
            for agent_id, agent_data in tasks_data['agents'].items():
                if agent_data.get('workspace') == str(self.workspace_path):
                    current_output = agent_data.get('aider_output', '')
                    new_output = self.get_output()
                    if new_output != current_output:
                        agent_data['aider_output'] = new_output
                        updated = True
                        logging.debug(f"[Session {self.session_id}] Updated output for agent {agent_id}")
                        logging.debug(f"[Session {self.session_id}] New output length: {len(new_output)}")
                    break
            
            if updated:
                save_tasks(tasks_data)
                logging.info(f"[Session {self.session_id}] Saved updated output to tasks.json")
        except Exception as e:
            logging.error(f"[Session {self.session_id}] Error updating output in tasks: {e}", exc_info=True)

    def get_output(self):
        """Get the current output buffer contents"""
        try:
            output = self.output_buffer.getvalue()
            logging.debug(f"[Session {self.session_id}] Retrieved output (length: {len(output)})")
            return output
        except Exception as e:
            logging.error(f"[Session {self.session_id}] Error getting output: {e}", exc_info=True)
            return ""

    def cleanup(self):
        """Clean up the aider session"""
        try:
            logging.info(f"[Session {self.session_id}] Starting cleanup")
            self._stop_event.set()
            if self.process:
                logging.info(f"[Session {self.session_id}] Terminating process {self.process.pid}")
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                    logging.info(f"[Session {self.session_id}] Process terminated successfully")
                except subprocess.TimeoutExpired:
                    logging.warning(f"[Session {self.session_id}] Process did not terminate, forcing kill")
                    self.process.kill()
            logging.info(f"[Session {self.session_id}] Cleanup completed")
        except Exception as e:
            logging.error(f"[Session {self.session_id}] Error during cleanup: {e}", exc_info=True)

def load_tasks():
    """Load tasks from tasks.json."""
    try:
        with open(TASKS_FILE, 'r') as f:
            data = json.load(f)
            if 'repository_url' not in data:
                data['repository_url'] = config_manager.get_repository_url()
            logging.debug(f"Loaded tasks data: {json.dumps(data, indent=2)}")
            return data
    except FileNotFoundError:
        logging.info("tasks.json not found, creating new data structure")
        return {
            "tasks": [],
            "agents": {},
            "repository_url": config_manager.get_repository_url()
        }
    except json.JSONDecodeError:
        logging.error("Error decoding tasks.json", exc_info=True)
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
        
        logging.debug(f"Saving tasks data: {json.dumps(data_to_save, indent=2)}")
        with open(TASKS_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logging.info("Successfully saved tasks data")
    except Exception as e:
        logging.error(f"Error saving tasks: {e}", exc_info=True)

def delete_agent(agent_id):
    """Delete a specific agent and clean up its workspace."""
    try:
        logging.info(f"Attempting to delete agent {agent_id}")
        tasks_data = load_tasks()
        
        # Find and remove the agent
        if agent_id in tasks_data['agents']:
            agent_data = tasks_data['agents'][agent_id]
            logging.info(f"Found agent {agent_id} in tasks data")
            
            # Cleanup aider session if it exists
            if agent_id in aider_sessions:
                logging.info(f"Cleaning up aider session for agent {agent_id}")
                aider_sessions[agent_id].cleanup()
                del aider_sessions[agent_id]
            
            # Remove workspace directory if it exists
            workspace = agent_data.get('workspace')
            if workspace and os.path.exists(workspace):
                try:
                    shutil.rmtree(workspace)
                    logging.info(f"Removed workspace for agent {agent_id}: {workspace}")
                except Exception as e:
                    logging.error(f"Could not remove workspace: {e}", exc_info=True)
            
            # Remove agent from tasks data
            del tasks_data['agents'][agent_id]
            save_tasks(tasks_data)
            
            logging.info(f"Successfully deleted agent {agent_id}")
            return True
        else:
            logging.warning(f"No agent found with ID {agent_id}")
            return False
    except Exception as e:
        logging.error(f"Error deleting agent: {e}", exc_info=True)
        return False

def initialiseCodingAgent(repository_url: str = None, task_description: str = None, num_agents: int = None):
    """Initialise coding agents with configurable agent count."""
    logging.info("Starting agent initialization")
    logging.debug(f"Parameters: repo_url={repository_url}, task={task_description}, num_agents={num_agents}")
    
    # Use provided num_agents or get default from config
    num_agents = num_agents or config_manager.get_default_agents_per_task()
    
    # Validate input
    if not task_description:
        logging.error("No task description provided")
        return None
    
    # Track created agent IDs
    created_agent_ids = []
    
    try:
        # Load tasks data to get repository URL
        tasks_data = load_tasks()
        if repository_url:
            tasks_data['repository_url'] = repository_url
            save_tasks(tasks_data)
            logging.info(f"Updated repository URL: {repository_url}")
        else:
            repository_url = tasks_data.get('repository_url')
            logging.info(f"Using existing repository URL: {repository_url}")
        
        for i in range(num_agents):
            logging.info(f"Creating agent {i+1} of {num_agents}")
            
            # Generate unique agent ID
            agent_id = str(uuid.uuid4())
            logging.info(f"Generated agent ID: {agent_id}")
            
            # Create temporary workspace directory
            agent_workspace = Path(tempfile.mkdtemp(prefix=f"agent_{agent_id}_"))
            logging.info(f"Created workspace at: {agent_workspace}")
            
            # Create standard directory structure
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
            logging.info("Created workspace directory structure")
                
            # Create task file in agent workspace
            task_file = agent_workspace / "current_task.txt"
            task_file.write_text(task_description)
            logging.info("Created task file")
            
            # Store current directory
            original_dir = Path.cwd()
            
            try:
                # Clone repository into repo subdirectory
                os.chdir(workspace_dirs["repo"])
                if not repository_url:
                    logging.error("No repository URL provided")
                    shutil.rmtree(agent_workspace)
                    continue
                
                logging.info(f"Cloning repository: {repository_url}")
                if not cloneRepository(repository_url):
                    logging.error("Failed to clone repository")
                    shutil.rmtree(agent_workspace)
                    continue
                
                # Get the cloned repository directory name
                repo_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and not d.startswith('.')]
                if not repo_dirs:
                    logging.error("No repository directory found after cloning")
                    shutil.rmtree(agent_workspace)
                    continue
                
                repo_dir = repo_dirs[0]
                full_repo_path = workspace_dirs["repo"] / repo_dir
                logging.info(f"Repository cloned to: {full_repo_path}")
                
                # Change to the cloned repository directory
                os.chdir(full_repo_path)
                
                # Create and checkout new branch
                branch_name = f"agent-{agent_id[:8]}"
                try:
                    subprocess.check_call(f"git checkout -b {branch_name}", shell=True)
                    logging.info(f"Created and checked out branch: {branch_name}")
                except subprocess.CalledProcessError:
                    logging.error("Failed to create new branch", exc_info=True)
                    shutil.rmtree(agent_workspace)
                    continue

                # Initialize aider session
                logging.info("Initializing aider session")
                aider_session = AiderSession(str(full_repo_path), task_description)
                if not aider_session.start():
                    logging.error("Failed to start aider session")
                    shutil.rmtree(agent_workspace)
                    continue

                # Store session in global dictionary
                aider_sessions[agent_id] = aider_session
                logging.info("Aider session started successfully")

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
            
            logging.info(f"Successfully initialized agent {agent_id}")
            created_agent_ids.append(agent_id)
        
        return created_agent_ids if created_agent_ids else None
        
    except Exception as e:
        logging.error(f"Error initializing coding agents: {e}", exc_info=True)
        return None

def cloneRepository(repository_url: str) -> bool:
    """Clone git repository using subprocess.check_call."""
    try:
        if not repository_url:
            logging.error("No repository URL provided")
            return False
        logging.info(f"Cloning repository: {repository_url}")
        subprocess.check_call(f"git clone {repository_url}", shell=True)
        return True
    except subprocess.CalledProcessError as e:
        logging.error(f"Git clone failed with exit code {e.returncode}", exc_info=True)
        return False

def critique_agent_progress(agent_id):
    """Critique the progress of a specific agent."""
    try:
        logging.info(f"Critiquing progress for agent {agent_id}")
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            logging.error(f"No agent found with ID {agent_id}")
            return None
        
        # Use repo_path for file search
        repo_path = agent_data.get('repo_path')
        if not repo_path:
            logging.error(f"No repo path found for agent {agent_id}")
            return None
            
        workspace = Path(repo_path)
        if not workspace.exists():
            logging.error(f"Workspace path does not exist: {workspace}")
            return None
        
        src_files = list(workspace.glob('**/*.py'))  # Check Python files
        logging.info(f"Found {len(src_files)} Python files in workspace")
        
        critique = {
            'files_created': len(src_files),
            'complexity': 'moderate',  # This would be a more sophisticated assessment
            'potential_improvements': []
        }
        
        # Update agent status based on critique
        agent_data['status'] = 'in_progress' if len(src_files) > 0 else 'pending'
        
        # Update aider output
        if agent_id in aider_sessions:
            output = aider_sessions[agent_id].get_output()
            agent_data['aider_output'] = output
            logging.debug(f"Updated aider output (length: {len(output)})")
        
        agent_data['last_critique'] = critique
        agent_data['last_updated'] = datetime.datetime.now().isoformat()
        
        save_tasks(tasks_data)
        logging.info(f"Completed critique for agent {agent_id}")
        return critique
    
    except Exception as e:
        logging.error(f"Error critiquing agent progress: {e}", exc_info=True)
        return None

def main_loop():
    """Main orchestration loop to manage agents."""
    logging.info("Starting main orchestration loop")
    try:
        while True:
            try:
                # Load current tasks and agents
                tasks_data = load_tasks()
                
                # Check each agent's progress
                for agent_id, agent_data in list(tasks_data['agents'].items()):
                    logging.info(f"Checking agent {agent_id}")
                    
                    # Critique progress
                    critique = critique_agent_progress(agent_id)
                    if critique:
                        agent_data['last_critique'] = critique
                        agent_data['last_updated'] = datetime.datetime.now().isoformat()
                    
                    # Update prompt file in temporary workspace
                    if agent_data.get('workspace'):
                        prompt_file = Path(agent_data['workspace']) / 'config' / 'prompt.txt'
                        prompt_file.parent.mkdir(parents=True, exist_ok=True)
                        prompt_data = {
                            'task': agent_data.get('task', ''),
                            'status': agent_data.get('status', 'unknown'),
                            'last_critique': critique if isinstance(critique, dict) else None,
                            'aider_output': agent_data.get('aider_output', '')
                        }
                        prompt_file.write_text(json.dumps(prompt_data, indent=4))
                        logging.debug(f"Updated prompt file for agent {agent_id}")
                
                # Save updated tasks
                save_tasks(tasks_data)
                
                # Wait before next check
                logging.info(f"Waiting {CHECK_INTERVAL} seconds before next check")
                sleep(CHECK_INTERVAL)
            
            except Exception as e:
                logging.error(f"Error in main loop iteration: {e}", exc_info=True)
                sleep(CHECK_INTERVAL)
                
    except KeyboardInterrupt:
        logging.info("Main loop interrupted by user")
        raise

if __name__ == "__main__":
    logging.info("Starting orchestrator")
    main_loop()
