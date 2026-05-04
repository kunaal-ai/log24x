import os
from deepeval.metrics import FaithfulnessMetric
from deepeval.test_case import LLMTestCase
from app.models.audit import AuditRequest, AuditResponse

class TruthCheckService:
    def __init__(self):
        self.threshold = 0.8 #anything lower is fail
        self.metric = FaithfulnessMetric(threshold=self.threshold)

    async def run_audit(self, data: AuditRequest) -> AuditResponse:
        test_case = LLMTestCase(
            input = data.prompt,
            actual_output=data.actual_output,
            retrieval_context=data.context
        )

        # measure faithfulness
        self.metric.measure(test_case)

        score = self.metric.score
        reasoning = self.metric.reason

        # formulate the response
        is_hallucination = score < self.threshold

        return AuditResponse(
            trust_score = round(score, 2),
            is_hallucination = is_hallucination,
            reasoning = reasoning,
            verdict="Pass" if not is_hallucination else "Fail"
        )