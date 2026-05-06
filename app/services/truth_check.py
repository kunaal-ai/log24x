import json
import os
import uuid
from datetime import datetime, timezone

from deepeval.metrics import FaithfulnessMetric
from deepeval.test_case import LLMTestCase
from app.models.audit import AuditRequest, AuditResponse


class TruthCheckService:
    def __init__(self, redis_client=None):
        self.threshold = 0.8
        self.redis = redis_client
        self.model_name = "gpt-4o-mini"

    async def run_audit(self, data: AuditRequest, user_key: str = None) -> AuditResponse:
        # 1. Setup the API Key (Priority: User Header > .env)
        api_key = user_key or os.getenv("OPENAI_API_KEY")
        
        if not api_key:
            raise ValueError("No OpenAI API Key found. Provide one in headers or .env")
              
        os.environ["OPENAI_API_KEY"] = api_key

        # 2. creates evaluator - Initialize Metric (DeepEval handles OpenAI connection automatically)
        metric = FaithfulnessMetric(
            threshold=self.threshold, 
            model=self.model_name
        )
        
        # data bundling 
        test_case = LLMTestCase(
            input=data.prompt,
            actual_output=data.actual_output,
            retrieval_context=data.context
        )

        # 3. Execute Audit - sends structured prompt(test_case), 
        # parse, calculate faithfulness score, 
        # store in metric.score, .reason, .success
        metric.measure(test_case)
        
        # 4. Save result to Redis
        audit_id = str(uuid.uuid4())
        audit_data = {
            "id": audit_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "prompt": data.prompt,
            "verdict": "Pass" if metric.score >= self.threshold else "Fail",
            "score": round(metric.score, 2),
            "reasoning": metric.reason,
        }
        if self.redis:
            await self.redis.set(f"audit:{audit_id}", json.dumps(audit_data))
        
        return AuditResponse(
            trust_score=round(metric.score, 2),
            is_hallucination=metric.score < self.threshold,
            reasoning=metric.reason,
            verdict="Pass" if metric.score >= self.threshold else "Fail"
        )