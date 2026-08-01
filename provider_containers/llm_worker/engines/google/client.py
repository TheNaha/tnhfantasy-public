import os
import json
import logging
from typing import Dict, Any, Optional

from fastapi.responses import StreamingResponse

from provider_core.base_client import BaseProviderClient
from provider_core.models import (
    InferenceRequest, DownloadRequest, ListModelsRequest, DeleteModelRequest,
    UploadFileRequest, ValidateModelsRequest,
    build_status_response, build_error_response
)


class GoogleProviderClient(BaseProviderClient):
    """
    Provider Client for LLM generation via Google Gemini API.
    """

    def __init__(self, provider_id: str, runtime_config: Dict[str, Any]):
        super().__init__(provider_id=provider_id, runtime_config=runtime_config)
        self.logger = logging.getLogger("provider_core.engines.google")
        self.api_key = os.environ.get("GOOGLE_API_KEY", "")

    async def get_health(self) -> Dict[str, Any]:
        return {
            "status": "healthy",
            "provider_id": self.provider_id,
            "engine": "google",
        }

    async def get_info(self) -> Dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "type": "google",
            "containerized": True,
        }

    async def inference(self, request: InferenceRequest) -> StreamingResponse:
        async def stream():
            try:
                import httpx
                workflow = request.workflow
                
                raw_messages = workflow.get("messages", [])
                
                # Gemini format expects {"role": "user"|"model", "parts": [{"text": "..."}]}
                # system instructions are sent separately.
                system_prompt = ""
                contents = []
                for m in raw_messages:
                    role = m.get("role")
                    if role == "system":
                        system_prompt += m.get("content", "") + "\n"
                    else:
                        g_role = "model" if role == "assistant" else "user"
                        contents.append({
                            "role": g_role,
                            "parts": [{"text": m.get("content", "")}]
                        })
                
                model_id = workflow.get("model") or "gemini-1.5-flash"
                
                payload = {
                    "contents": contents,
                }
                
                if system_prompt:
                    payload["systemInstruction"] = {
                        "role": "user",
                        "parts": [{"text": system_prompt.strip()}]
                    }

                url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:streamGenerateContent?alt=sse&key={self.api_key}"

                headers = {
                    "Content-Type": "application/json"
                }

                async with httpx.AsyncClient() as client:
                    async with client.stream(
                        "POST",
                        url,
                        headers=headers,
                        json=payload,
                        timeout=120.0,
                    ) as response:
                        response.raise_for_status()

                        full_content = ""

                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line:
                                continue

                            if line.startswith("data: "):
                                data_str = line[6:]
                                try:
                                    data = json.loads(data_str)
                                    candidates = data.get("candidates", [])
                                    if candidates:
                                        content_parts = candidates[0].get("content", {}).get("parts", [])
                                        if content_parts:
                                            text = content_parts[0].get("text", "")
                                            if text:
                                                full_content += text
                                                event = {
                                                    "type": "progress",
                                                    "progress": 0,
                                                    "message": text,
                                                }
                                                yield json.dumps(event) + "\n"
                                except json.JSONDecodeError:
                                    pass

                        output = {"role": "assistant", "content": full_content}

                        yield json.dumps({
                            "type": "completed",
                            "outputs": [output],
                        }) + "\n"

            except Exception as e:
                self.logger.error(f"Error during inference: {str(e)}")
                yield json.dumps(build_error_response(str(e), retryable=True, code=500)) + "\n"

        return StreamingResponse(stream(), media_type="application/x-ndjson")

    async def setup_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Setup complete", provider=self.provider_id)

    async def download_model(self, request: DownloadRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def list_models(self, request: Optional[ListModelsRequest] = None) -> Dict[str, Any]:
        models = ["gemini-1.5-flash", "gemini-1.5-pro", "gemini-1.0-pro"]
        return {"files": [{"path": m, "name": m} for m in models]}

    async def delete_model(self, request: DeleteModelRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def get_file(self, path: str):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Not supported")

    async def delete_file(self, path: str) -> Dict[str, Any]:
        return build_error_response("Not supported", retryable=False, code=404)

    async def upload_file(self, request: UploadFileRequest) -> Dict[str, Any]:
        return build_error_response("Not supported", retryable=False, code=404)

    async def deploy(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def validate_models(self, request: ValidateModelsRequest) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def validate_all_models(self) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)

    async def get_object_info(self) -> Dict[str, Any]:
        return {"object_info": {}}

    async def run_reconciliation(self) -> Dict[str, Any]:
        return build_status_response("success", "Not applicable", provider=self.provider_id)
