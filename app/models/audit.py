from pydantic import BaseModel, Field
from typing import List, Optional

class AuditRequest(BaseModel):
    # specify what the API expects to receive, 
    # pydantic automatically validates incoming JSON against this schema
    # Bad requests get rejected early (missing fields, wrong types)
    prompt: str = Field(..., example="What is the refund policy")
    context: List[str] = Field(..., example=["Refunds are allowed within 30 days with a receipt."])
    actual_output: str = Field(..., example="You can get a refund in 30 days if you have your receipt.")
    model_name: str = "gpt-4o"

class AuditResponse(BaseModel):
    # specifies what API will RETURN
    trust_score: float = Field(..., description="Score from 0.0 to 1.0 (1.0 is perfect)")
    gemini_score: float
    groq_score: float 
    is_hallucination: bool
    reasoning: Optional[str] = Field(None, description="Explanation from the Judge LLM")
    verdict: str = Field(..., description="Pass or Fail based on threshold (0.8)")
