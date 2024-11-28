import os
from typing import Dict, Any, List
from mcp_sdk import MCPServer, Capability, Request, Response

class OrchestratorMCPServer(MCPServer):
    def __init__(self):
        super().__init__("orchestrator")
        self.register_capability(
            Capability(
                name="manage_agents",
                description="Manage coding agents and their tasks",
                methods=[
                    "create_agent",
                    "delete_agent",
                    "get_agent_status",
                    "update_agent_task"
                ]
            )
        )
        
    async def handle_request(self, request: Request) -> Response:
        method = request.method
        params = request.params
        
        if method == "create_agent":
            return await self.create_agent(params)
        elif method == "delete_agent":
            return await self.delete_agent(params)
        elif method == "get_agent_status":
            return await self.get_agent_status(params)
        elif method == "update_agent_task":
            return await self.update_agent_task(params)
        
        return Response(error="Method not supported")

    async def create_agent(self, params: Dict[str, Any]) -> Response:
        try:
            repository_url = params.get("repository_url")
            task_description = params.get("task_description")
            num_agents = params.get("num_agents", 1)
            
            from orchestrator import initialiseCodingAgent
            agent_ids = initialiseCodingAgent(
                repository_url=repository_url,
                task_description=task_description,
                num_agents=num_agents
            )
            
            return Response(result={"agent_ids": agent_ids})
        except Exception as e:
            return Response(error=str(e))

    async def delete_agent(self, params: Dict[str, Any]) -> Response:
        try:
            agent_id = params.get("agent_id")
            if not agent_id:
                return Response(error="agent_id is required")
                
            from orchestrator import delete_agent
            success = delete_agent(agent_id)
            
            return Response(result={"success": success})
        except Exception as e:
            return Response(error=str(e))

    async def get_agent_status(self, params: Dict[str, Any]) -> Response:
        try:
            agent_id = params.get("agent_id")
            if not agent_id:
                return Response(error="agent_id is required")
                
            from orchestrator import load_tasks
            tasks_data = load_tasks()
            agent_data = tasks_data.get("agents", {}).get(agent_id)
            
            if not agent_data:
                return Response(error="Agent not found")
                
            return Response(result=agent_data)
        except Exception as e:
            return Response(error=str(e))

    async def update_agent_task(self, params: Dict[str, Any]) -> Response:
        try:
            agent_id = params.get("agent_id")
            new_task = params.get("task")
            
            if not agent_id or not new_task:
                return Response(error="agent_id and task are required")
                
            from orchestrator import load_tasks, save_tasks
            tasks_data = load_tasks()
            
            if agent_id not in tasks_data.get("agents", {}):
                return Response(error="Agent not found")
                
            tasks_data["agents"][agent_id]["task"] = new_task
            save_tasks(tasks_data)
            
            return Response(result={"success": True})
        except Exception as e:
            return Response(error=str(e))

def start_server():
    server = OrchestratorMCPServer()
    server.start()

if __name__ == "__main__":
    start_server()
