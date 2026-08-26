from fastapi import APIRouter
from pydantic import BaseModel

from services.context_builder import estimate_tokens

router = APIRouter()


class EstimateTokensRequest(BaseModel):
    text: str


@router.post("/estimate-tokens")
def estimate_tokens_endpoint(data: EstimateTokensRequest):
    """tiktoken-based token count for arbitrary text (composer meters etc.)."""
    return {"tokens": estimate_tokens(data.text or "")}
