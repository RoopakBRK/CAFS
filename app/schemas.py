from pydantic import BaseModel, HttpUrl
from typing import Optional, List, Dict, Any

class ForensicsResult(BaseModel):
    manipulation_score: float
    is_high_risk: bool
    status: str
    details: Optional[List[str]] = []
    # LLM Analysis Fields
    llm_analysis: Optional[str] = None
    llm_risk_score: Optional[float] = None
    llm_confidence: Optional[float] = None
    llm_reasoning: Optional[str] = None
    # REMOVED: metadata field

class ExtractionResult(BaseModel):
    candidate_name: Optional[str] = None
    certificate_id: Optional[str] = None
    issuer_url: Optional[str] = None
    raw_text_snippet: Optional[str] = None 

class VerificationResult(BaseModel):
    is_verified: bool
    message: str
    trusted_domain: bool

class CertificateAnalysisResponse(BaseModel):
    filename: str
    final_verdict: str
    forensics: ForensicsResult
    extraction: ExtractionResult
    verification: VerificationResult