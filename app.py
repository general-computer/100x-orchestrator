from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from utils.env_utils import EnvManager
from flask_socketio import SocketIO, emit
from utils.installation_utils import AiderInstallationManager
from orchestrator import (
    initialiseCodingAgent, 
    main_loop, 
    load_tasks, 
    save_tasks, 
    delete_agent,
    normalize_path,
    validate_agent_paths,
    aider_sessions,
    output_queue,
    AiderSession
)
import os
import threading
import queue
import json
from pathlib import Path
import datetime
import logging
import logging.handlers


# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            'app_debug.log',
            maxBytes=10485760,
            backupCount=5
        ),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


app = Flask(__name__)
app.config['SECRET_KEY'] = os.urandom(24)
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet', ping_timeout=10)

def broadcast_output():
    """Background thread to broadcast output updates via WebSocket"""
    logger.info("Starting WebSocket broadcast thread")
    while True:
        try:
            update = output_queue.get()
            socketio.emit('output_update', update, namespace='/agents')
            logger.debug(f"Broadcasted update for agent {update.get('agent_id')}")
        except Exception as e:
            logger.error(f"Error broadcasting output: {str(e)}", exc_info=True)
        finally:
            socketio.sleep(0)

# Start broadcast thread
broadcast_thread = threading.Thread(target=broadcast_output, daemon=True)
broadcast_thread.start()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/settings')
def settings():
    """Render the settings page"""
    api_keys = EnvManager.get_api_keys()
    return render_template('settings.html', 
                         openai_key=api_keys['openai_api_key'],
                         anthropic_key=api_keys['anthropic_api_key'],
                         openrouter_key=api_keys['openrouter_api_key'])

@app.route('/save_settings', methods=['POST'])
def save_settings():
    """Save API keys to .env file"""
    try:
        data = request.get_json()
        success = EnvManager.save_api_keys(data)
        
        if success:
            return jsonify({
                'success': True,
                'message': 'Settings saved successfully'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to save settings'
            })
    except Exception as e:
        logger.error(f"Error saving settings: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'message': f'Error: {str(e)}'
        })

@app.route('/tasks/tasks.json')
def serve_tasks_json():
    return send_from_directory('tasks', 'tasks.json')

@app.route('/agents')
def agent_view():
    try:
        tasks_data = load_tasks()
        agents = tasks_data.get('agents', {})
        
        # Basic data needed for initial render
        for agent_id, agent in agents.items():
            agent['debug_urls'] = {
                'info': f'/debug/agent/{agent_id}',
                'validate': f'/debug/validate_paths/{agent_id}'
            }
            
            # Ensure minimum required fields
            if 'workspace' not in agent:
                agent['workspace'] = normalize_path(os.path.join('workspaces', agent_id))
            else:
                agent['workspace'] = normalize_path(agent['workspace'])
                
            if 'repo_path' in agent:
                agent['repo_path'] = normalize_path(agent['repo_path'])
            
            if 'aider_output' not in agent:
                agent['aider_output'] = ''
                
            if 'status' not in agent:
                agent['status'] = 'pending'
        
        return render_template('agent_view.html', 
                             agents=agents, 
                             initial_state=json.dumps({
                                 'has_agents': bool(agents),
                                 'agent_count': len(agents)
                             }))
    except Exception as e:
        logger.error(f"Error in agent_view: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)}), 500

@app.route('/create_agent', methods=['POST'])
def create_agent():
    try:
        # Use AiderInstallationManager to check installation
        aider_manager = AiderInstallationManager()
        is_installed, error_msg = aider_manager.check_aider_installation()
        
        if not is_installed:
            return jsonify({
                'success': False,
                'error': error_msg or 'Aider is not installed. Please run: pip install aider-chat',
                'needs_installation': True
            }), 500
        
        data = request.get_json()
        repo_url = data.get('repo_url')
        tasks = data.get('tasks', [])
        num_agents = data.get('num_agents', 1)
        
        if not repo_url or not tasks:
            return jsonify({'error': 'Repository URL and tasks are required'}), 400
        
        if isinstance(tasks, str):
            tasks = [tasks]
        
        tasks_data = load_tasks()
        created_agents = []
        
        for task_description in tasks:
            os.environ['REPOSITORY_URL'] = repo_url
            agent_ids = initialiseCodingAgent(
                repository_url=repo_url, 
                task_description=task_description, 
                num_agents=num_agents
            )
            
            if agent_ids:
                created_agents.extend(agent_ids)
                if task_description not in tasks_data['tasks']:
                    tasks_data['tasks'].append(task_description)
        
        tasks_data['repo_url'] = repo_url
        tasks_data['agents'] = tasks_data.get('agents', {})
        for agent_id in created_agents:
            tasks_data['agents'][agent_id] = {
                'task': tasks_data['tasks'][-1],
                'repo_url': repo_url,
                'workspace': os.path.join('workspaces', agent_id)
            }
        
        save_tasks(tasks_data)
        
        def check_and_start_main_loop():
            for thread in threading.enumerate():
                if thread.name == 'OrchestratorMainLoop':
                    return
            
            thread = threading.Thread(target=main_loop, name='OrchestratorMainLoop')
            thread.daemon = True
            thread.start()
        
        check_and_start_main_loop()
        
        if created_agents:
            return jsonify({
                'success': True,
                'agent_ids': created_agents,
                'message': f'Agents {", ".join(created_agents)} created successfully'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create any agents'
            }), 500
            
    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
        
        
@socketio.on('retry_agent', namespace='/agents')
def handle_retry_agent(data):
    try:
        agent_id = data.get('agent_id')
        if not agent_id:
            raise ValueError("No agent_id provided")
            
        tasks_data = load_tasks()
        if agent_id not in tasks_data['agents']:
            raise ValueError(f"Agent {agent_id} not found")
            
        aider_session = aider_sessions.get(agent_id)
        if aider_session:
            aider_session.cleanup()
            del aider_sessions[agent_id]
            
        # Reinitialize the agent
        agent_data = tasks_data['agents'][agent_id]
        new_session = AiderSession(agent_data['repo_path'], agent_data['task'])
        if new_session.start():
            aider_sessions[agent_id] = new_session
            agent_data['status'] = 'in_progress'
            agent_data['last_updated'] = datetime.datetime.now().isoformat()
            save_tasks(tasks_data)
            
            emit('agent_retry_result', {
                'success': True,
                'agent_id': agent_id,
                'timestamp': datetime.datetime.now().isoformat()
            })
        else:
            raise RuntimeError(f"Failed to restart agent {agent_id}")
            
    except Exception as e:
        logger.error(f"Error retrying agent: {str(e)}", exc_info=True)
        emit('agent_retry_result', {
            'success': False,
            'agent_id': agent_id,
            'error': str(e),
            'timestamp': datetime.datetime.now().isoformat()
        })
        
@socketio.on('request_update', namespace='/agents')
def handle_request_update():
    try:
        tasks_data = load_tasks()
        for agent_id, agent_data in tasks_data['agents'].items():
            emit('output_update', {
                'agent_id': agent_id,
                'output': agent_data.get('aider_output', ''),
                'status': agent_data.get('status', 'pending'),
                'status_reason': agent_data.get('status_reason'),
                'error_details': agent_data.get('error_details'),
                'timestamp': datetime.datetime.now().isoformat()
            })
    except Exception as e:
        logger.error(f"Error handling update request: {str(e)}", exc_info=True)


@app.route('/delete_agent/<agent_id>', methods=['DELETE'])
def remove_agent(agent_id):
    try:
        tasks_data = load_tasks()
        
        if agent_id not in tasks_data['agents']:
            logger.error(f"No agent found with ID {agent_id}")
            return jsonify({
                'success': False, 
                'error': f'Agent {agent_id} not found'
            }), 404
        
        # Store agent data before deletion for logging
        agent_data = tasks_data['agents'][agent_id]
        logger.info(f"Found agent {agent_id} with workspace: {agent_data.get('workspace')}")
        
        deletion_result = delete_agent(agent_id)
        
        if deletion_result:
            # Remove from tasks data after successful deletion
            del tasks_data['agents'][agent_id]
            save_tasks(tasks_data)
            
            # Emit WebSocket event for real-time UI update
            socketio.emit('agent_deleted', {
                'agent_id': agent_id,
                'timestamp': datetime.datetime.now().isoformat()
            }, namespace='/agents')
            
            logger.info(f"Successfully deleted agent {agent_id}")
            return jsonify({
                'success': True,
                'message': f'Agent {agent_id} deleted successfully'
            })
        else:
            logger.error(f"Failed to delete agent {agent_id}")
            return jsonify({
                'success': False,
                'error': f'Failed to delete agent {agent_id}'
            }), 500
    
    except Exception as e:
        logger.error(f"Error deleting agent: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    
    except Exception as e:
        logger.error(f"Error deleting agent: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/debug/agent/<agent_id>')
def debug_agent(agent_id):
    try:
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            return jsonify({
                'error': f'Agent {agent_id} not found'
            }), 404
            
        workspace_path = normalize_path(agent_data.get('workspace'))
        repo_path = normalize_path(agent_data.get('repo_path'))
        
        aider_session = aider_sessions.get(agent_id)
        aider_workspace = normalize_path(aider_session.workspace_path) if aider_session else None
        
        debug_info = {
            'agent_id': agent_id,
            'paths': {
                'workspace': {
                    'raw': agent_data.get('workspace'),
                    'normalized': workspace_path,
                    'exists': os.path.exists(workspace_path) if workspace_path else False
                },
                'repo_path': {
                    'raw': agent_data.get('repo_path'),
                    'normalized': repo_path,
                    'exists': os.path.exists(repo_path) if repo_path else False
                },
                'aider_workspace': {
                    'raw': aider_session.workspace_path if aider_session else None,
                    'normalized': aider_workspace,
                    'exists': os.path.exists(aider_workspace) if aider_workspace else False
                }
            },
            'aider_session': {
                'exists': aider_session is not None,
                'output_buffer_length': len(aider_session.get_output()) if aider_session else 0,
                'session_id': aider_session.session_id if aider_session else None
            },
            'agent_data': {
                'status': agent_data.get('status'),
                'created_at': agent_data.get('created_at'),
                'last_updated': agent_data.get('last_updated'),
                'aider_output_length': len(agent_data.get('aider_output', '')),
                'task': agent_data.get('task')
            }
        }
        
        return jsonify(debug_info)
        
    except Exception as e:
        logger.error(f"Error in debug endpoint: {str(e)}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500

@app.route('/debug/validate_paths/<agent_id>')
def debug_validate_paths(agent_id):
    try:
        tasks_data = load_tasks()
        agent_data = tasks_data['agents'].get(agent_id)
        
        if not agent_data:
            return jsonify({
                'error': f'Agent {agent_id} not found'
            }), 404
        
        aider_session = aider_sessions.get(agent_id)
        
        validation_results = {
            'agent_id': agent_id,
            'paths': {
                'workspace': {
                    'raw': agent_data.get('workspace'),
                    'normalized': normalize_path(agent_data.get('workspace'))
                },
                'repo_path': {
                    'raw': agent_data.get('repo_path'),
                    'normalized': normalize_path(agent_data.get('repo_path'))
                },
                'aider_workspace': {
                    'raw': aider_session.workspace_path if aider_session else None,
                    'normalized': normalize_path(aider_session.workspace_path) if aider_session else None
                }
            },
            'validation': {
                'has_aider_session': aider_session is not None
            }
        }
        
        if aider_session:
            validation_results['validation']['path_match'] = validate_agent_paths(
                agent_id, 
                aider_session.workspace_path
            )
            validation_results['validation']['output_length'] = len(aider_session.get_output())
            validation_results['validation']['stored_output_length'] = len(agent_data.get('aider_output', ''))
        
        return jsonify(validation_results)
        
    except Exception as e:
        logger.error(f"Error in path validation debug endpoint: {str(e)}", exc_info=True)
        return jsonify({
            'error': str(e)
        }), 500

@socketio.on('connect', namespace='/agents')
def handle_connect():
    try:
        logger.info(f"Client connected: {request.sid}")
        tasks_data = load_tasks()
        agents = tasks_data.get('agents', {})
        
        # Send initial state to newly connected client
        emit('connection_established', {
            'has_agents': bool(agents),
            'agent_count': len(agents),
            'status': 'connected'
        }, namespace='/agents', to=request.sid)
        
        # Send current state of each agent
        for agent_id, agent in agents.items():
            emit('output_update', {
                'agent_id': agent_id,
                'output': agent.get('aider_output', ''),
                'status': agent.get('status', 'pending'),
                'timestamp': datetime.datetime.now().isoformat()
            }, namespace='/agents', to=request.sid)
    except Exception as e:
        logger.error(f"Error in handle_connect: {str(e)}", exc_info=True)
        emit('connection_error', {'error': str(e)}, namespace='/agents', to=request.sid)
        
        

@socketio.on('disconnect', namespace='/agents')
def handle_disconnect():
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on_error(namespace='/agents')
def handle_error(e):
    logger.error(f"WebSocket error: {str(e)}", exc_info=True)
    emit('connection_error', {'error': str(e)})

if __name__ == '__main__':
    logger.info("Starting application")
    socketio.run(app, debug=True)
