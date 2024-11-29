import os
import json
import traceback
import subprocess
import sys
import uuid
from pathlib import Path
import shutil
import tempfile
from time import sleep
from litellm import completion
import threading
import datetime
import queue
import io
import errno
import logging
import logging.handlers
from flask_socketio import emit
from utils.installation_utils import AiderInstallationManager


logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            'orchestrator_debug.log',
            maxBytes=10485760,
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'

DEFAULT_AGENTS_PER_TASK = 2
MODEL_NAME = os.environ.get('LITELLM_MODEL', 'anthropic/claude-3-5-sonnet-20240620')
CONFIG_FILE = Path("config.json")
CHECK_INTERVAL = 30

aider_sessions = {}
output_queue = queue.Queue()
tools, available_functions = [], {}

class AiderNotFoundError(Exception):
    """Raised when aider is not installed or not found in PATH"""
    pass

def check_aider_installation():
    """Check if aider is installed and available"""
    aider_manager = AiderInstallationManager()
    is_installed, _ = aider_manager.check_aider_installation()
    return is_installed

def start_aider_session(workspace_path, task, cmd_override=None):
    """Start aider with appropriate error handling"""
    aider_manager = AiderInstallationManager()
    aider_path = aider_manager.get_aider_command()
    
    if not check_aider_installation():
        logger.error("Aider is not installed or not found in PATH")
        raise AiderNotFoundError(
            "Aider is not installed. Please install it using:\n"
            "pip install aider-chat"
        )
    
    try:
        if cmd_override:
            cmd = cmd_override
        else:
            cmd = f'"{aider_path}" --mini --message "{task}"'
        
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        env['PYTHONIOENCODING'] = 'utf-8'
        
        process = subprocess.Popen(
            cmd,
            shell=True,
            cwd=str(Path(workspace_path).resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            startupinfo=startupinfo,
            text=True,
            bufsize=1,
            universal_newlines=True,
            env=env
        )
        
        return process
    except Exception as e:
        logger.error(f"Failed to start aider: {str(e)}")
        raise

def normalize_path(path_str):
    if not path_str:
        return None
    try:
        path = Path(path_str).resolve()
        normalized = str(path).replace('\\', '/')
        logger.debug(f"Path normalization: {path_str} -> {normalized}")
        return normalized
    except Exception as e:
        logger.error(f"Error normalizing path {path_str}: {e}", exc_info=True)
        return None

def validate_agent_paths(agent_id, workspace_path):
    try:
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            logger.error(f"No agent found with ID {agent_id}")
            return False
            
        workspace_path = normalize_path(workspace_path)
        agent_workspace = normalize_path(agent_data.get('workspace'))
        agent_repo_path = normalize_path(agent_data.get('repo_path'))
        
        logger.info(f"Validating paths for agent {agent_id}")
        logger.info(f"  Workspace path: {workspace_path}")
        logger.info(f"  Agent workspace: {agent_workspace}")
        logger.info(f"  Agent repo path: {agent_repo_path}")
        
        return workspace_path in [agent_workspace, agent_repo_path]
        
    except Exception as e:
        logger.error(f"Error validating agent paths: {e}", exc_info=True)
        return False
    
class AgentStatus:
    """Agent status constants"""
    PENDING = 'pending'
    IN_PROGRESS = 'in_progress'
    ERROR = 'error'
    STALLED = 'stalled'
    COMPLETED = 'completed'

    @classmethod
    def get_display_name(cls, status):
        """Get user-friendly display name for status"""
        return {
            cls.PENDING: 'Pending',
            cls.IN_PROGRESS: 'In Progress',
            cls.ERROR: 'Error',
            cls.STALLED: 'Stalled',
            cls.COMPLETED: 'Completed'
        }.get(status, status)

    @classmethod
    def is_error_state(cls, status):
        """Check if status represents an error condition"""
        return status in [cls.ERROR, cls.STALLED]

class AiderSession:
    def __init__(self, workspace_path, task):
        self.error_count = 0
        self.consecutive_empty_reads = 0
        self.max_empty_reads = 10
        self.last_output_time = datetime.datetime.now()
        self.workspace_path = normalize_path(workspace_path)
        self.task = task
        self.output_buffer = io.StringIO()
        self.process = None
        self.output_queue = queue.Queue()
        self._stop_event = threading.Event()
        self.session_id = str(uuid.uuid4())[:8]
        self.agent_id = None
        
        logger.info(f"[Session {self.session_id}] Initialized with workspace: {self.workspace_path}")
        
        for agent_id in aider_sessions:
            if validate_agent_paths(agent_id, self.workspace_path):
                self.agent_id = agent_id
                logger.info(f"[Session {self.session_id}] Associated with agent {self.agent_id}")
                break

    def start(self):
     try:
        logger.info(f"[Session {self.session_id}] Starting aider session in workspace: {self.workspace_path}")
        
        tasks_data = load_tasks()
        for agent_id, agent_data in tasks_data['agents'].items():
            if normalize_path(agent_data.get('workspace')) == self.workspace_path:
                self.agent_id = agent_id
                break
        
        try:
            self.process = start_aider_session(self.workspace_path, self.task)
            logger.info(f"[Session {self.session_id}] Process started with PID: {self.process.pid}")
        except AiderNotFoundError as e:
            logger.error(f"[Session {self.session_id}] Aider not found: {str(e)}")
            self._update_agent_status('error')
            if self.agent_id:
                tasks_data = load_tasks()
                if self.agent_id in tasks_data['agents']:
                    agent_data = tasks_data['agents'][self.agent_id]
                    agent_data['status'] = 'error'
                    agent_data['status_reason'] = str(e)
                    agent_data['error_details'] = {
                        'error_count': 1,
                        'last_output_time': datetime.datetime.now().isoformat(),
                        'consecutive_empty_reads': 0
                    }
                    save_tasks(tasks_data)
            return False
        
        # Start the threads for reading output
        stdout_thread = threading.Thread(
            target=self._read_output,
            args=(self.process.stdout, "stdout"),
            daemon=True,
            name=f"stdout-{self.session_id}"
        )
        stderr_thread = threading.Thread(
            target=self._read_output,
            args=(self.process.stderr, "stderr"),
            daemon=True,
            name=f"stderr-{self.session_id}"
        )
        process_thread = threading.Thread(
            target=self._process_output,
            daemon=True,
            name=f"process-{self.session_id}"
        )
        
        stdout_thread.start()
        stderr_thread.start()
        process_thread.start()
        
        for thread in [stdout_thread, stderr_thread, process_thread]:
            if not thread.is_alive():
                logger.error(f"[Session {self.session_id}] Thread {thread.name} failed to start")
                return False
            logger.info(f"[Session {self.session_id}] Thread {thread.name} is running")
        
        return True
        
     except Exception as e:
        logger.error(f"[Session {self.session_id}] Failed to start aider session: {e}", exc_info=True)
        if self.agent_id:
            self._update_agent_status('error')
        return False

    def _read_output(self, pipe, pipe_name):
        try:
            logger.info(f"[Session {self.session_id}] Started reading from {pipe_name}")
            for line in iter(pipe.readline, ''):
                if self._stop_event.is_set():
                    break
                    
                if line.strip():  # Reset counters on valid output
                    self.consecutive_empty_reads = 0
                    self.last_output_time = datetime.datetime.now()
                    
                    # Detect error messages
                    if any(error_sign in line.lower() for error_sign in [
                        'error:', 'exception:', 'failed:', 'traceback:',
                        'could not', 'unable to', 'permission denied'
                    ]):
                        self.error_count += 1
                        logger.warning(f"[Session {self.session_id}] Error detected: {line.strip()}")
                else:
                    self.consecutive_empty_reads += 1
                
                logger.debug(f"[Session {self.session_id}] {pipe_name} received: {line.strip()}")
                self.output_queue.put(line)
                pipe.flush()
                
                # Check for stalled state
                if self.consecutive_empty_reads >= self.max_empty_reads:
                    self._update_agent_status(AgentStatus.STALLED)
                    logger.warning(f"[Session {self.session_id}] Agent appears to be stalled")
                
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error reading from {pipe_name}: {e}", exc_info=True)
            self._update_agent_status(AgentStatus.ERROR)
        finally:
            pipe.close()
            logger.info(f"[Session {self.session_id}] Closed {pipe_name} pipe")
            
            
    def _update_agent_status(self, status):
        try:
            if not self.agent_id:
                return
                
            tasks_data = load_tasks()
            if self.agent_id in tasks_data['agents']:
                agent_data = tasks_data['agents'][self.agent_id]
                old_status = agent_data.get('status')
                
                if old_status != status:
                    agent_data['status'] = status
                    agent_data['status_changed_at'] = datetime.datetime.now().isoformat()
                    agent_data['status_reason'] = self._get_status_reason(status)
                    
                    if status in [AgentStatus.ERROR, AgentStatus.STALLED]:
                        agent_data['error_details'] = {
                            'error_count': self.error_count,
                            'consecutive_empty_reads': self.consecutive_empty_reads,
                            'last_output_time': self.last_output_time.isoformat()
                        }
                    
                    save_tasks(tasks_data)
                    
                    # Emit status update
                    update = {
                        'agent_id': self.agent_id,
                        'status': status,
                        'status_reason': agent_data['status_reason'],
                        'error_details': agent_data.get('error_details'),
                        'timestamp': datetime.datetime.now().isoformat()
                    }
                    output_queue.put(update)
                    
                    logger.info(f"[Session {self.session_id}] Updated agent {self.agent_id} status to {status}")
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error updating agent status: {e}", exc_info=True)
            
    def _get_status_reason(self, status):
        if status == AgentStatus.ERROR:
            return f"Encountered {self.error_count} errors during execution"
        elif status == AgentStatus.STALLED:
            time_since_output = datetime.datetime.now() - self.last_output_time
            return f"No output received for {time_since_output.seconds} seconds"
        return None
    
    def check_health(self):
        """Periodically check agent health and update status"""
        try:
            if not self.process:
                return
                
            # Check if process is still running
            if self.process.poll() is not None:
                logger.warning(f"[Session {self.session_id}] Process has terminated")
                self._update_agent_status(AgentStatus.ERROR)
                return
            
            # Check time since last output
            time_since_output = datetime.datetime.now() - self.last_output_time
            if time_since_output.seconds > 300:  # 5 minutes
                logger.warning(f"[Session {self.session_id}] No output for {time_since_output.seconds} seconds")
                self._update_agent_status(AgentStatus.STALLED)
                return
            
            # Check error threshold
            if self.error_count > 5:
                logger.warning(f"[Session {self.session_id}] Error threshold exceeded")
                self._update_agent_status(AgentStatus.ERROR)
                return
                
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error in health check: {e}", exc_info=True)
            self._update_agent_status(AgentStatus.ERROR)

    def _process_output(self):
        logger.info(f"[Session {self.session_id}] Started output processing thread")
        buffer_update_count = 0
        
        while not self._stop_event.is_set():
            try:
                try:
                    line = self.output_queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                
                with threading.Lock():
                    self.output_buffer.seek(0, 2)
                    self.output_buffer.write(line)
                    buffer_update_count += 1
                    
                    current_output = self.get_output()
                    
                    if self.agent_id:
                        update = {
                            'agent_id': self.agent_id,
                            'output': current_output,
                            'timestamp': datetime.datetime.now().isoformat()
                        }
                        output_queue.put(update)
                        logger.debug(f"[Session {self.session_id}] Queued WebSocket update for agent {self.agent_id}")
                    
                    if buffer_update_count % 5 == 0 or any(keyword in line for keyword in ['Error:', 'Warning:', 'Success:']):
                        self._update_output_in_tasks()
                        logger.debug(f"[Session {self.session_id}] Updated tasks.json after {buffer_update_count} updates")
                
            except Exception as e:
                logger.error(f"[Session {self.session_id}] Error processing output: {e}", exc_info=True)

    def _update_output_in_tasks(self):
        try:
            tasks_data = load_tasks()
            updated = False
            current_output = self.get_output()
            current_workspace = normalize_path(self.workspace_path)
            
            if self.agent_id:
                agent_data = tasks_data['agents'].get(self.agent_id)
                if agent_data:
                    if not agent_data.get('repo_path'):
                        agent_data['repo_path'] = current_workspace
                    
                    if current_output != agent_data.get('aider_output', ''):
                        agent_data['aider_output'] = current_output
                        agent_data['last_updated'] = datetime.datetime.now().isoformat()
                        updated = True
            else:
                for agent_id, agent_data in tasks_data['agents'].items():
                    agent_workspace = normalize_path(agent_data.get('workspace'))
                    agent_repo_path = normalize_path(agent_data.get('repo_path'))
                    
                    if current_workspace == agent_workspace and not agent_repo_path:
                        agent_data['repo_path'] = current_workspace
                    
                    if current_workspace in [agent_workspace, agent_repo_path]:
                        if current_output != agent_data.get('aider_output', ''):
                            agent_data['aider_output'] = current_output
                            agent_data['last_updated'] = datetime.datetime.now().isoformat()
                            updated = True
                            self.agent_id = agent_id
                        break
            
            if updated:
                save_tasks(tasks_data)
                logger.info(f"[Session {self.session_id}] Updated output for agent {self.agent_id}")
            
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error updating output in tasks: {e}", exc_info=True)

    def get_output(self):
        try:
            pos = self.output_buffer.tell()
            self.output_buffer.seek(0)
            output = self.output_buffer.read()
            self.output_buffer.seek(pos)
            return output
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error getting output: {e}", exc_info=True)
            return ""

    def cleanup(self):
        try:
            logger.info(f"[Session {self.session_id}] Starting cleanup")
            self._stop_event.set()
            if self.process:
                logger.info(f"[Session {self.session_id}] Terminating process {self.process.pid}")
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    logger.warning(f"[Session {self.session_id}] Process did not terminate, forcing kill")
                    self.process.kill()
            logger.info(f"[Session {self.session_id}] Cleanup completed")
        except Exception as e:
            logger.error(f"[Session {self.session_id}] Error during cleanup: {e}", exc_info=True)

def load_tasks():
    try:
        with open(CONFIG_FILE, 'r') as f:
            data = json.load(f)
            if 'repository_url' not in data:
                data['repository_url'] = ""
                
            for agent_id, agent_data in data.get('agents', {}).items():
                if 'workspace' in agent_data:
                    agent_data['workspace'] = normalize_path(agent_data['workspace'])
                if 'repo_path' in agent_data:
                    agent_data['repo_path'] = normalize_path(agent_data['repo_path'])
            
            logger.debug(f"Loaded tasks data: {json.dumps(data, indent=2)}")
            return data
    except FileNotFoundError:
        logger.info("config.json not found, creating new data structure")
        return {
            "tasks": [],
            "agents": {},
            "repository_url": ""
        }
    except Exception as e:
        logger.error(f"Error loading tasks: {e}", exc_info=True)
        return {
            "tasks": [],
            "agents": {},
            "repository_url": ""
        }

def save_tasks(tasks_data):
    try:
        data_to_save = {
            "tasks": tasks_data.get("tasks", []),
            "agents": {},
            "repository_url": tasks_data.get("repository_url", "")
        }
        
        for agent_id, agent_data in tasks_data.get("agents", {}).items():
            data_to_save["agents"][agent_id] = {
                'workspace': normalize_path(agent_data.get('workspace')),
                'repo_path': normalize_path(agent_data.get('repo_path')),
                'task': agent_data.get('task'),
                'status': agent_data.get('status'),
                'created_at': agent_data.get('created_at'),
                'last_updated': agent_data.get('last_updated'),
                'aider_output': agent_data.get('aider_output', ''),
                'last_critique': agent_data.get('last_critique')
            }
            
            logger.debug(f"Saving agent {agent_id} with normalized paths:")
            logger.debug(f"  workspace: {data_to_save['agents'][agent_id]['workspace']}")
            logger.debug(f"  repo_path: {data_to_save['agents'][agent_id]['repo_path']}")
        
        with open(CONFIG_FILE, 'w') as f:
            json.dump(data_to_save, f, indent=4)
        logger.info("Successfully saved tasks data")
    except Exception as e:
        logger.error(f"Error saving tasks: {e}", exc_info=True)

def delete_agent(agent_id):
    try:
        logger.info(f"Attempting to delete agent {agent_id}")
        tasks_data = load_tasks()
        
        if agent_id in tasks_data['agents']:
            agent_data = tasks_data['agents'][agent_id]
            
            if agent_id in aider_sessions:
                logger.info(f"Cleaning up aider session for agent {agent_id}")
                aider_sessions[agent_id].cleanup()
                del aider_sessions[agent_id]
            
            workspace = agent_data.get('workspace')
            if workspace and os.path.exists(workspace):
                try:
                    shutil.rmtree(workspace)
                    logger.info(f"Removed workspace for agent {agent_id}: {workspace}")
                except Exception as e:
                    logger.error(f"Could not remove workspace: {e}", exc_info=True)
            
            del tasks_data['agents'][agent_id]
            save_tasks(tasks_data)
            
            update = {
                'agent_id': agent_id,
                'type': 'deletion',
                'timestamp': datetime.datetime.now().isoformat()
            }
            output_queue.put(update)
            
            return True
        else:
            logger.warning(f"No agent found with ID {agent_id}")
            return False
    except Exception as e:
        logger.error(f"Error deleting agent: {e}", exc_info=True)
        return False

def initialiseCodingAgent(repository_url: str = None, task_description: str = None, num_agents: int = None):
    logger.info("Starting agent initialization")
    logger.debug(f"Parameters: repo_url={repository_url}, task={task_description}, num_agents={num_agents}")
    
    try:
        # First check if aider is installed
        if not check_aider_installation():
            logger.error("Aider is not installed. Cannot create agents.")
            return None
            
        num_agents = num_agents or DEFAULT_AGENTS_PER_TASK
        
        if not task_description:
            logger.error("No task description provided")
            return None
        
        created_agent_ids = []
        
        tasks_data = load_tasks()
        if repository_url:
            tasks_data['repository_url'] = repository_url
            save_tasks(tasks_data)
            logger.info(f"Updated repository URL: {repository_url}")
        else:
            repository_url = tasks_data.get('repository_url')
            logger.info(f"Using existing repository URL: {repository_url}")
        
        for i in range(num_agents):
            logger.info(f"Creating agent {i+1} of {num_agents}")
            
            agent_id = str(uuid.uuid4())
            logger.info(f"Generated agent ID: {agent_id}")
            
            agent_workspace = Path(tempfile.mkdtemp(prefix=f"agent_{agent_id}_")).resolve()
            logger.info(f"Created workspace at: {agent_workspace}")
            
            workspace_dirs = {
                "src": agent_workspace / "src",
                "tests": agent_workspace / "tests", 
                "docs": agent_workspace / "docs", 
                "config": agent_workspace / "config", 
                "repo": agent_workspace / "repo"
            }
            
            for dir_path in workspace_dirs.values():
                dir_path.mkdir(parents=True, exist_ok=True)
            logger.info("Created workspace directory structure")
                
            task_file = agent_workspace / "current_task.txt"
            task_file.write_text(task_description)
            logger.info("Created task file")
            
            original_dir = Path.cwd()
            repo_dir = None
            full_repo_path = None
            
            try:
                os.chdir(workspace_dirs["repo"])
                if not repository_url:
                    logger.error("No repository URL provided")
                    shutil.rmtree(agent_workspace)
                    continue
                
                logger.info(f"Cloning repository: {repository_url}")
                if not cloneRepository(repository_url):
                    logger.error("Failed to clone repository")
                    shutil.rmtree(agent_workspace)
                    continue
                
                repo_dirs = [d for d in os.listdir('.') if os.path.isdir(d) and not d.startswith('.')]
                if not repo_dirs:
                    logger.error("No repository directory found after cloning")
                    shutil.rmtree(agent_workspace)
                    continue
                
                repo_dir = repo_dirs[0]
                full_repo_path = workspace_dirs["repo"] / repo_dir
                full_repo_path = full_repo_path.resolve()
                logger.info(f"Repository cloned to: {full_repo_path}")
                
                os.chdir(full_repo_path)
                
                branch_name = f"agent-{agent_id[:8]}"
                try:
                    subprocess.check_call(f"git checkout -b {branch_name}", shell=True)
                    logger.info(f"Created and checked out branch: {branch_name}")
                except subprocess.CalledProcessError:
                    logger.error("Failed to create new branch", exc_info=True)
                    shutil.rmtree(agent_workspace)
                    continue

                logger.info("Initializing aider session")
                aider_session = AiderSession(str(full_repo_path), task_description)
                if not aider_session.start():
                    logger.error("Failed to start aider session")
                    shutil.rmtree(agent_workspace)
                    continue

                aider_sessions[agent_id] = aider_session
                logger.info("Aider session started successfully")

            finally:
                os.chdir(original_dir)
            
            tasks_data['agents'][agent_id] = {
                'workspace': normalize_path(agent_workspace),
                'repo_path': normalize_path(full_repo_path) if full_repo_path else None,
                'task': task_description,
                'status': 'pending',
                'created_at': datetime.datetime.now().isoformat(),
                'last_updated': datetime.datetime.now().isoformat(),
                'aider_output': ''
            }
            save_tasks(tasks_data)
            
            logger.info(f"Successfully initialized agent {agent_id}")
            created_agent_ids.append(agent_id)
        
        return created_agent_ids if created_agent_ids else None
        
    except Exception as e:
        logger.error(f"Error initializing coding agents: {e}", exc_info=True)
        return None

def cloneRepository(repository_url: str) -> bool:
    try:
        if not repository_url:
            logger.error("No repository URL provided")
            return False
        logger.info(f"Cloning repository: {repository_url}")
        subprocess.check_call(f"git clone {repository_url}", shell=True)
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"Git clone failed with exit code {e.returncode}", exc_info=True)
        return False

def critique_agent_progress(agent_id):
    try:
        logger.info(f"Critiquing progress for agent {agent_id}")
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            logger.error(f"No agent found with ID {agent_id}")
            return None
        
        repo_path = agent_data.get('repo_path')
        if not repo_path:
            logger.error(f"No repo path found for agent {agent_id}")
            agent_data.update({
                'status': AgentStatus.ERROR,
                'status_reason': 'Repository path not found'
            })
            return None
            
        workspace = Path(repo_path)
        if not workspace.exists():
            logger.error(f"Workspace path does not exist: {workspace}")
            agent_data.update({
                'status': AgentStatus.ERROR,
                'status_reason': f'Workspace path does not exist: {workspace}'
            })
            return None
        
        src_files = list(workspace.glob('**/*.py'))
        logger.info(f"Found {len(src_files)} Python files in workspace")
        
        critique = {
            'files_created': len(src_files),
            'complexity': 'moderate',
            'potential_improvements': []
        }
        
        # Update status based on progress and health
        aider_session = aider_sessions.get(agent_id)
        if aider_session:
            if aider_session.error_count > 5:
                agent_data['status'] = AgentStatus.ERROR
                agent_data['status_reason'] = f'Error threshold exceeded ({aider_session.error_count} errors)'
            elif aider_session.consecutive_empty_reads >= aider_session.max_empty_reads:
                agent_data['status'] = AgentStatus.STALLED
                agent_data['status_reason'] = 'No output received for extended period'
            elif len(src_files) > 0:
                agent_data['status'] = AgentStatus.IN_PROGRESS
            else:
                agent_data['status'] = AgentStatus.PENDING
                
            output = aider_session.get_output()
            agent_data['aider_output'] = output
            if output:
                agent_data['last_updated'] = datetime.datetime.now().isoformat()
        else:
            agent_data['status'] = AgentStatus.ERROR
            agent_data['status_reason'] = 'Agent session not found'
        
        agent_data['last_critique'] = critique
        
        save_tasks(tasks_data)
        logger.info(f"Completed critique for agent {agent_id}")
        return critique
    
    except Exception as e:
        logger.error(f"Error critiquing agent progress: {e}", exc_info=True)
        agent_data.update({
            'status': AgentStatus.ERROR,
            'status_reason': f'Error during critique: {str(e)}'
        })
        return None

def main_loop():
    logger.info("Starting main orchestration loop")
    while True:
        try:
            tasks_data = load_tasks()
            current_time = datetime.datetime.now().isoformat()
            
            for agent_id, agent_data in list(tasks_data['agents'].items()):
                logger.info(f"Processing agent {agent_id}")
                
                aider_session = aider_sessions.get(agent_id)
                if not aider_session:
                    agent_data.update({
                        'status': AgentStatus.ERROR,
                        'status_reason': 'Aider session not found or terminated',
                        'error_details': {
                            'error_count': 1,
                            'last_output_time': current_time,
                            'consecutive_empty_reads': 0
                        },
                        'last_updated': current_time
                    })
                    continue
                    
                # Run health check
                aider_session.check_health()
                agent_output = aider_session.get_output()
                
                # Update agent data
                agent_data.update({
                    'aider_output': agent_output,
                    'last_updated': current_time
                })
                
                # Check agent state and critique
                critique = critique_agent_progress(agent_id)
                if critique:
                    agent_data['last_critique'] = critique
                
                # Force error status if process has terminated
                if aider_session.process and aider_session.process.poll() is not None:
                    agent_data.update({
                        'status': AgentStatus.ERROR,
                        'status_reason': 'Agent process has terminated unexpectedly',
                        'error_details': {
                            'error_count': aider_session.error_count,
                            'last_output_time': aider_session.last_output_time.isoformat(),
                            'consecutive_empty_reads': aider_session.consecutive_empty_reads
                        }
                    })
                
                # Emit update via WebSocket
                status_update = {
                    'agent_id': agent_id,
                    'status': agent_data.get('status'),
                    'status_reason': agent_data.get('status_reason'),
                    'error_details': agent_data.get('error_details'),
                    'output': agent_output,
                    'timestamp': current_time
                }
                output_queue.put(status_update)
                
                # Update stored data
                tasks_data['agents'][agent_id] = agent_data
            
            save_tasks(tasks_data)
            logger.info(f"Waiting {CHECK_INTERVAL} seconds before next check")
            sleep(CHECK_INTERVAL)
            
        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    logger.info("Starting orchestrator")
    main_loop()
