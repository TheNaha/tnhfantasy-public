import json
import logging
from typing import Any

from sqlmodel import Session

from core.entities import JobStatus
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
        message_payload: dict[str, Any], 
        context: list[dict[str, Any]],
        provider_id: str | None = None
    ) -> dict[str, Any]:
        """
        Processes an LLM assistant response (which may contain tool_calls), 
        running any tool calls autonomously until a plain text response is returned.
        
        NOTE: This method expects `message_payload` to be an ASSISTANT message 
        (potentially with tool_calls). To start a new turn from a user message, 
        use `run_chat_turn()` instead.
        """
        current_context = list(context)
        current_context.append(message_payload)
        
        loop_count = 0
        
        while loop_count < self.max_tool_calls:
            latest_msg = current_context[-1]
            
            # 1. Check if the LLM wants to call tools
            tool_calls = latest_msg.get("tool_calls", [])
            
            if not tool_calls:
                # No more tools to run; return the final text response
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
            next_llm_response = await self._request_llm_completion(current_context, provider_id)
            current_context.append(next_llm_response)
            
            loop_count += 1
            
        raise ToolExecutionLimitExceeded(f"Exceeded max tool calls ({self.max_tool_calls})")

    async def run_chat_turn(
        self,
        user_message: str,
        context: list[dict[str, Any]],
        provider_id: str | None = None,
        character_system_prompt: str | None = None,
    ) -> dict[str, Any]:
        """
        Main entry point for a single chat turn.
        1. Optionally prepends a character system prompt.
        2. Adds the user message to context.
        3. Gets an initial LLM completion.
        4. Runs the agentic tool loop on the response.
        Returns the final assistant message dict.
        """
        current_context = list(context)

        # Inject character system prompt if provided and not already first
        if character_system_prompt:
            if not current_context or current_context[0].get("role") != "system":
                current_context.insert(0, {"role": "system", "content": character_system_prompt})

        # Append user message
        current_context.append({"role": "user", "content": user_message})

        # Get initial LLM completion
        logger.info(f"Dispatching initial LLM completion for chat turn (provider={provider_id})")
        llm_response = await self._request_llm_completion(current_context, provider_id)

        # Run agentic tool loop on LLM response
        # Pass context *without* the user message so process_llm_response can append llm_response cleanly
        return await self.process_llm_response(llm_response, current_context[:-1], provider_id)

    async def _execute_tool(self, tool_call: dict[str, Any]) -> dict[str, Any]:
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

    async def _tool_generate_image(self, args: dict[str, Any]) -> dict[str, Any]:
        """
        Tool: Generates an image and returns the asset reference.
        """
        import asyncio
        prompt = args.get("prompt", "a beautiful fantasy landscape")
        
        logger.info(f"Executing generate_image tool with prompt: {prompt}")
        
        # Spawn an image generation job and wait for it
        job = await self.job_service.create_job(
            task_type="image",
            workflow={"prompt": prompt},
            metadata={"source": "tool_call"}
        )
        
        while True:
            job_status = await self.job_service.get_job(job.id)
            if job_status.status == JobStatus.COMPLETED:
                outputs = job_status.outputs or []
                asset_url = outputs[0].get("url", f"/gallery/generated_{hash(prompt)}.png") if outputs else f"/gallery/generated_{hash(prompt)}.png"
                return {
                    "status": "success",
                    "asset_url": asset_url,
                    "prompt_used": prompt
                }
            elif job_status.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                return {"status": "error", "error": job_status.error or "Job failed or cancelled"}
            await asyncio.sleep(1.0)
        
    async def _request_llm_completion(self, context: list[dict[str, Any]], provider_id: str | None) -> dict[str, Any]:
        """
        Dispatches the completion job to the LLM worker.
        """
        import asyncio
        workflow = {
            "messages": context,
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "generate_image",
                        "description": "Generate an image based on a prompt.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "prompt": {
                                    "type": "string",
                                    "description": "The prompt to generate the image."
                                }
                            },
                            "required": ["prompt"]
                        }
                    }
                }
            ]
        }
        
        job = await self.job_service.create_job(
            task_type="text",
            workflow=workflow,
            metadata={"provider_id": provider_id} if provider_id else {}
        )
        
        while True:
            job_status = await self.job_service.get_job(job.id)
            if job_status.status == JobStatus.COMPLETED:
                outputs = job_status.outputs or []
                if outputs:
                    return outputs[0]
                return {"role": "assistant", "content": ""}
            elif job_status.status in (JobStatus.FAILED, JobStatus.CANCELLED):
                raise OrchestratorError(f"LLM completion job failed: {job_status.error}")
            await asyncio.sleep(1.0)
