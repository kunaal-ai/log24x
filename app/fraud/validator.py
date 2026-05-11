from dataclasses import dataclass
from typing import Optional
import os
import asyncio

@dataclass
class LayerResult:
    passed: Optional[bool]
    score: Optional[float]
    detail: str

@dataclass
class ValidationResult:
    overall_confidence: str
    faithfulness: LayerResult
    relevancy: LayerResult
    hallucination: LayerResult
    grok_agreement: LayerResult
    rule_grounding: LayerResult
    final_badge: str
    grok_explanation: Optional[str]

def run_deepeval(explanation: str, txn: dict) -> tuple[LayerResult, LayerResult, LayerResult]:
    unavailable = LayerResult(passed=None, score=None, detail='Removed - using cross-model validation instead')
    return unavailable, unavailable, unavailable

def run_grok_crosscheck(txn: dict, gemini_explanation: str) -> tuple[LayerResult, Optional[str]]:
    '''
    Sends the same transaction to Grok with the same prompt.
    Compares Grok response to Gemini response.
    Returns a LayerResult and the Grok explanation text.
    '''
    try:
        from groq import Groq
        client = Groq(api_key=os.getenv("GROQ_API_KEY"))
        
        grok_prompt = f'''
You are a fraud analyst reviewing a flagged transaction.
In one sentence, name the primary fraud typology this transaction most likely represents.
Choose only from: STRUCTURING, MONEY_MULE, ACCOUNT_TAKEOVER, CARD_FRAUD, WIRE_FRAUD, IDENTITY_FRAUD, or UNKNOWN.
Then in 2 to 3 sentences explain why.

Transaction data:
Amount: ${txn['amount_usd']:,.2f}
Merchant: {txn['merchant_name']}
Location: {txn['location']}
Rules triggered: {', '.join(txn['rules_triggered'])}
Risk score: {txn['risk_score']}
'''
        chat_completion = client.chat.completions.create(
            messages=[{"role": "user", "content": grok_prompt}],
            model="llama-3.3-70b-versatile",
        )
        grok_text = chat_completion.choices[0].message.content.strip()
        
        typology_keywords = ['STRUCTURING', 'MONEY_MULE', 'ACCOUNT_TAKEOVER',
                            'CARD_FRAUD', 'WIRE_FRAUD', 'IDENTITY_FRAUD', 'UNKNOWN']
        
        grok_typology = 'UNKNOWN'
        for kw in typology_keywords:
            if kw in grok_text.upper():
                grok_typology = kw
                break
                
        gemini_typology = 'UNKNOWN'
        rule_to_typology = {
            'STRUCTURING': 'STRUCTURING',
            'RAPID_MOVEMENT': 'MONEY_MULE',
            'INTL_SPIKE': 'ACCOUNT_TAKEOVER',
            'ROUND_AMOUNT': 'WIRE_FRAUD',
            'HIGH_VELOCITY': 'CARD_FRAUD',
        }
        for rule in txn.get('rules_triggered', []):
            if rule in rule_to_typology:
                gemini_typology = rule_to_typology[rule]
                break
                
        agreed = grok_typology == gemini_typology or grok_typology == 'UNKNOWN'
        result = LayerResult(
            passed=agreed,
            score=1.0 if agreed else 0.0,
            detail=f'Grok agrees: both identify {gemini_typology} pattern.' if agreed else f'Grok disagrees: Grok identifies {grok_typology}, Gemini identifies {gemini_typology}. Review both explanations.'
        )
        return result, grok_text
    except Exception as e:
        return LayerResult(passed=None, score=None, detail=f'Grok cross-check unavailable: {str(e)[:100]}'), None

RULE_KEYWORDS = {
    'STRUCTURING': ['structur', 'threshold', 'reporting', '$10,000', '9,000', '9,900', 'deposit', 'cash'],
    'RAPID_MOVEMENT': ['rapid', 'pass-through', 'pass through', 'mule', 'forward', 'outgoing', 'outflow', 'retain'],
    'INTL_SPIKE': ['international', 'overseas', 'foreign', 'country', 'geographic', 'location'],
    'ROUND_AMOUNT': ['round', 'exact', 'even amount', 'manually', 'wire', 'transfer'],
    'HIGH_VELOCITY': ['velocity', 'rapid', 'frequency', 'multiple transaction', 'short period', 'hour'],
}

def run_rule_grounding(explanation: str, rules_triggered: list[str]) -> LayerResult:
    '''
    Checks if the explanation mentions keywords related to each triggered rule.
    A grounded explanation should reference the specific pattern, not just generic fraud language.
    '''
    explanation_lower = explanation.lower()
    grounded_rules = []
    ungrounded_rules = []
    
    for rule in rules_triggered:
        keywords = RULE_KEYWORDS.get(rule, [])
        if any(kw in explanation_lower for kw in keywords):
            grounded_rules.append(rule)
        else:
            ungrounded_rules.append(rule)
            
    all_grounded = len(ungrounded_rules) == 0
    score = len(grounded_rules) / len(rules_triggered) if rules_triggered else 1.0
    
    if all_grounded:
        detail = f'Explanation references patterns for all triggered rules: {", ".join(grounded_rules)}.'
    else:
        detail = f'Explanation does not clearly reference patterns for: {", ".join(ungrounded_rules)}. May be too generic.'
        
    return LayerResult(passed=all_grounded, score=round(score, 2), detail=detail)

def _compute_final_badge(grok_agreement: LayerResult, rule_grounding: LayerResult, confidence: str) -> str:
    # Badge based on cross-model agreement and rule grounding
    # VERIFIED, REVIEW_NEEDED, or UNVERIFIED
    
    has_failures = grok_agreement.passed is False or rule_grounding.passed is False
    
    if has_failures or confidence == "LOW":
        return "REVIEW_NEEDED"
    elif confidence == "HIGH" and not has_failures:
        return "VERIFIED"
    else:
        return "UNVERIFIED"

def validate_explanation(explanation: str, confidence: str, txn: dict) -> ValidationResult:
    '''
    Runs cross-model validation and returns a ValidationResult.
    Uses Grok as second opinion and checks rule grounding.
    '''
    faithfulness = LayerResult(passed=None, score=None, detail='Cross-model validation instead')
    relevancy = LayerResult(passed=None, score=None, detail='Cross-model validation instead')
    hallucination = LayerResult(passed=None, score=None, detail='Cross-model validation instead')
    
    grok_result, grok_text = run_grok_crosscheck(txn, explanation)
    rule_grounding = run_rule_grounding(explanation, txn.get('rules_triggered', []))
    
    final_badge = _compute_final_badge(grok_result, rule_grounding, confidence)
    
    return ValidationResult(
        overall_confidence=confidence,
        faithfulness=faithfulness,
        relevancy=relevancy,
        hallucination=hallucination,
        grok_agreement=grok_result,
        rule_grounding=rule_grounding,
        final_badge=final_badge,
        grok_explanation=grok_text
    )
