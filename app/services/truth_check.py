import os
import json
import asyncio
from datetime import datetime
from google import genai
from groq import Groq
from deepeval.metrics import FaithfulnessMetric
from deepeval.test_case import LLMTestCase
from deepeval.models import DeepEvalBaseLLM
from app.models.audit import AuditRequest, AuditResponse

# 1. Custom Wrapper for Gemini 2.5 (2026 Stable)
class GeminiJudge(DeepEvalBaseLLM):
    def __init__(self, model_name):
        self.model_name = model_name
        self.client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt
        )
        return response.text

    async def a_generate(self, prompt: str) -> str:
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self):
        return self.model_name

# 2. Custom Wrapper for Groq (Llama 3.3)
class GroqJudge(DeepEvalBaseLLM):
    def __init__(self, model_name):
        self.model_name = model_name
        self.client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    def load_model(self):
        return self.client

    def generate(self, prompt: str) -> str:
        chat_completion = self.client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model=self.model_name,
        )
        return chat_completion.choices[0].message.content

    async def a_generate(self, prompt: str) -> str:
        return await asyncio.to_thread(self.generate, prompt)

    def get_model_name(self):
        return self.model_name

# 3. Main Audit Service
class TruthCheckService:
    def __init__(self, redis_client):
        self.threshold = 0.8
        self.redis = redis_client
        
        # Initialize 2026 stable endpoints
        self.gemini = GeminiJudge("gemini-2.5-flash")
        self.groq = GroqJudge("llama-3.3-70b-versatile")

    async def run_single_audit(self, judge_obj, test_case: LLMTestCase):
        """Helper to run audit using the specific model object."""
        try:
            metric = FaithfulnessMetric(threshold=self.threshold, model=judge_obj)
            # Run the synchronous deepeval measure in a background thread
            await asyncio.to_thread(metric.measure, test_case)
            return {
                "score": round(float(metric.score), 2),
                "reason": str(metric.reason)
            }
        except Exception as e:
            return {"score": 0.0, "reason": f"Provider Error: {str(e)}"}

    async def run_audit(self, data: AuditRequest, audit_id: str) -> AuditResponse:
        test_case = LLMTestCase(
            input=data.prompt,
            actual_output=data.actual_output,
            retrieval_context=data.context
        )

        # Run both judges in parallel for speed
        results = await asyncio.gather(
            self.run_single_audit(self.gemini, test_case),
            self.run_single_audit(self.groq, test_case)
        )
        
        gemini_res, groq_res = results[0], results[1]

        # We prioritize Gemini for the final score, but store both for comparison
        score = gemini_res["score"]
        verdict = "Pass" if score >= self.threshold else "Fail"

        audit_entry = {
            "id": audit_id,
            "timestamp": datetime.now().isoformat(),
            "prompt": data.prompt,
            "context": json.dumps(data.context),
            "actual_output": data.actual_output,
            "verdict": verdict,
            "trust_score": score,
            "gemini_score": gemini_res["score"],
            "groq_score": groq_res["score"],
            "reasoning": f"Gemini: {gemini_res['reason']} | Groq: {groq_res['reason']}"
        }
        
        # Store in Redis
        await self.redis.hset(f"audit:{audit_id}", mapping=audit_entry)
        await self.redis.lpush("audit_history", audit_id)

        return AuditResponse(
            trust_score=score,
            gemini_score=gemini_res["score"],   # <-- add this
            groq_score=groq_res["score"],  
            is_hallucination=score < self.threshold,
            reasoning=audit_entry["reasoning"],
            verdict=verdict
        )