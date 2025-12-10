import io
import logging
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.concurrency import run_in_threadpool
from pdf2image import convert_from_bytes
from app.config import config

logger = logging.getLogger(__name__)
logger.setLevel(config.LOG_LEVEL)

# Import Schemas
from app.schemas import (
    CertificateAnalysisResponse, 
    ForensicsResult, 
    ExtractionResult, 
    VerificationResult
)

# Import Agents (Using the correct Class Names)
from app.agents.forensics import ForensicsAgent
from app.agents.extraction import ExtractionAgent
from app.agents.verification import VerificationAgent

app = FastAPI(title="Multi-Agent Certificate Verifier")

# Initialize Agents
forensics_agent = ForensicsAgent()
extraction_agent = ExtractionAgent()
verification_agent = VerificationAgent()

@app.post("/verify", response_model=CertificateAnalysisResponse)
async def verify_certificate(file: UploadFile = File(...)):
    """
    Orchestrates the workflow:
    1. Forensics (ELA/Photoshop Detection)
    2. Extraction (OCR)
    3. Verification (URL & Domain Check)
    """
    
    # 1. Read the raw file bytes
    file_bytes = await file.read()
    
    image_bytes = None

    # 2. Pre-processing: Handle PDF vs Image
    if file.content_type == "application/pdf":
        try:
            # Convert first page of PDF to Image
            images = convert_from_bytes(file_bytes)
            if not images:
                raise HTTPException(status_code=400, detail="PDF is empty or unreadable.")
            
            # Save the PIL image to a byte stream to mimic a standard image upload
            img_byte_arr = io.BytesIO()
            images[0].save(img_byte_arr, format='PNG')
            image_bytes = img_byte_arr.getvalue()
            
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Failed to process PDF: {str(e)}")

    elif file.content_type.startswith("image/"):
        image_bytes = file_bytes
    
    else:
        raise HTTPException(status_code=400, detail="File must be an image (JPEG/PNG) or a PDF.")

    try:
        # --- STAGE 1: FORENSICS (Check for Photoshop) ---
        # Run in threadpool to prevent blocking the server
        forensics_data = await run_in_threadpool(forensics_agent.analyze, image_bytes)
        
        # --- STAGE 2: EXTRACTION (OCR) ---
        # Extraction is CPU-bound (OCR), so we run it in a threadpool
        extraction_result = await run_in_threadpool(extraction_agent.extract, image_bytes)

        # --- STAGE 3: VERIFICATION (URL Check) ---
        # Verification is I/O-bound (HTTP requests), so we await it directly (it's now async)
        verification_result = await verification_agent.verify(extraction_result)

        # --- STAGE 4: FINAL VERDICT LOGIC ---
        final_verdict = "UNVERIFIED"

        if forensics_data.is_high_risk:
            final_verdict = "FLAGGED (High Risk)"
        elif verification_result.is_verified:
            final_verdict = "VERIFIED"
        else:
            final_verdict = "UNVERIFIED"

        return CertificateAnalysisResponse(
            filename=file.filename,
            final_verdict=final_verdict,
            forensics=forensics_data,
            extraction=extraction_result,
            verification=verification_result
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))