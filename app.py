from flask import Flask, render_template, request, jsonify
from orchestrator import initialiseCodingAgent, main_loop
import os
import threading
import json
from pathlib import Path

app = Flask(__name__)

def load_tasks():
    """Load tasks from tasks.json."""
    tasks_file = Path('tasks/tasks.json')
    try:
        with open(tasks_file, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"tasks": [], "agents": {}}

def save_tasks(tasks_data):
    """Save tasks to tasks.json."""
    tasks_file = Path('tasks/tasks.json')
    try:
        with open(tasks_file, 'w') as f:
            json.dump(tasks_data, f, indent=4)
    except Exception as e:
        print(f"Error saving tasks: {e}")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/create_agent', methods=['POST'])
def create_agent():
    try:
        data = request.get_json()
        repo_url = data.get('repo_url')
        tasks = data.get('tasks', [])
        
        if not repo_url or not tasks:
            return jsonify({'error': 'Repository URL and tasks are required'}), 400
        
        # Ensure tasks is a list
        if isinstance(tasks, str):
            tasks = [tasks]
        
        # Load existing tasks
        tasks_data = load_tasks()
        
        # Initialize agents for each task
        created_agents = []
        for task_description in tasks:
            # Set environment variable for repo URL
            os.environ['REPOSITORY_URL'] = repo_url
            
            # Initialize agent
            agent_id = initialiseCodingAgent(repo_url, task_description)
            
            if agent_id:
                created_agents.append(agent_id)
                # Add task to tasks list if not already present
                if task_description not in tasks_data['tasks']:
                    tasks_data['tasks'].append(task_description)
        
        # Save updated tasks
        save_tasks(tasks_data)
        
        # Start main loop in a separate thread if not already running
        def check_and_start_main_loop():
            # Check if main loop thread is already running
            for thread in threading.enumerate():
                if thread.name == 'OrchestratorMainLoop':
                    return
            
            # Start main loop if not running
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
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

if __name__ == '__main__':
    app.run(debug=True)
