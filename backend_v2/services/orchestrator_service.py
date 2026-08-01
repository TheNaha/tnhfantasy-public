import json
import logging
from typing import List, Dict, Any, Optional

from sqlmodel import Session
from core.entities import Job, JobStatus, TaskType
from infrastructure.database import get_session
from services.job_service import JobService

logger = logging.getLogger("orchestrator")

class OrchestratorError(Exception):
    pass

class ToolExecutionLimitExceeded(OrchestratorError):
    pass

class AgenticOrchestrator:
    """
    Manages autonomous loops for Agentic workflows (e.g., Roleplay Chatbots).
    Intercepts tool calls, orchestrates tool execution (like image generation),
    and feeds the results back into the LLM until the final response is ready.
    """
    
    def __init__(self, session: Session, max_tool_calls: int = 5):
        self.session = session
        self.job_service = JobService(session)
        self.max_tool_calls = max_tool_calls
        
    async def process_llm_response(
        self, 
        message_payload: Dict[str, Any], 
        context: List[Dict[str, Any]],
        provider_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Processes a raw response from the LLM, handling tool calls autonomously.
        Returns the final user-facing response after all tool loops are resolved.
        """
        current_context = list(context)
        current_context.append(message_payload)
        
        loop_count = 0
        
        while loop_count < self.max_tool_calls:
            latest_msg = current_context[-1]
            
            # 1. Check if the LLM wants to call tools
            tool_calls = latest_msg.get("tool_calls", [])
            
            if not tool_calls:
                # No more tools to run, return the final message
                return latest_msg
            
            logger.info(f"Agent requested {len(tool_calls)} tool calls. Loop: {loop_count}")
            
            # 2. Execute the tools (Autonomous Execution)
            tool_results = []
            for tool_call in tool_calls:
                try:
                    result = await self._execute_tool(tool_call)
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_call.get("function", {}).get("name"),
                        "content": json.dumps(result)
                    })
                except Exception as e:
                    logger.error(f"Tool execution failed: {e}")
                    tool_results.append({
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_call.get("function", {}).get("name"),
                        "content": json.dumps({"error": str(e)})
                    })
            
            current_context.extend(tool_results)
            
            # 3. Request next step from LLM with tool results
            # In a real implementation, we would call the LLM worker here
            # via a provider/worker request.
            # For now, we simulate the LLM's next response as a placeholder.
            next_llm_response = await self._request_llm_completion(current_context, provider_id)
            current_context.append(next_llm_response)
            
            loop_count += 1
            
        raise ToolExecutionLimitExceeded(f"Exceeded max tool calls ({self.max_tool_calls})")

    async def _execute_tool(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """
        Executes a single tool call based on its function name and arguments.
        """
        function = tool_call.get("function", {})
        name = function.get("name")
        try:
            args = json.loads(function.get("arguments", "{}"))
        except json.JSONDecodeError:
            args = {}
            
        if name == "generate_image":
            return await self._tool_generate_image(args)
        
        raise OrchestratorError(f"Unknown tool: {name}")

    async def _tool_generate_image(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        Tool: Generates an image and returns the asset reference.
        """
        prompt = args.get("prompt", "a beautiful fantasy landscape")
        
        # Simulate creating an image generation job
        # In full implementation, we'd enqueue a Job to the image worker
        # and wait for completion.
        logger.info(f"Executing generate_image tool with prompt: {prompt}")
        
        return {
            "status": "success",
            "asset_url": f"/gallery/generated_{hash(prompt)}.png",
            "prompt_used": prompt
        }
        
    async def _request_llm_completion(self, context: List[Dict[str, Any]], provider_id: Optional[str]) -> Dict[str, Any]:
        """
        Stub for actually dispatching the completion job to the LLM worker.
        """
        # TODO: Implement actual LLM worker dispatch
        return {
            "role": "assistant",
            "content": "I have processed your request.",
            "tool_calls": []
        }
