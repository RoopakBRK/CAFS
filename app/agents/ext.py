"""
Enhanced Extraction Agent with better error handling and integration
Compatible with your IssuerName enum and schemas
"""

import pytesseract
from PIL import Image, ImageEnhance, ImageFilter
import io
import json
import re
from mistralai import Mistral
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class ExtractionAgent:
    """
    Enhanced certificate extraction agent using OCR (Tesseract) and 
    LLM-based cleanup (Mistral) for structured data extraction.
    
    Integrates with IssuerName enum for standardized issuer matching.
    """

    def __init__(self, api_key: str):
        """
        Initialize extraction agent
        
        Args:
            api_key: Mistral API key
        """
        self.client = Mistral(api_key=api_key)
        self.model = "mistral-large-latest"

    def _preprocess_image(self, image: Image.Image) -> Image.Image:
        """
        Preprocess image to improve OCR accuracy
        
        Args:
            image: Input PIL Image
            
        Returns:
            Preprocessed PIL Image
        """
        try:
            # Convert to grayscale
            image = image.convert('L')
            
            # Increase contrast
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(2.0)
            
            # Sharpen
            image = image.filter(ImageFilter.SHARPEN)
            
            return image
        except Exception as e:
            logger.warning(f"Image preprocessing failed: {e}")
            return image

    def _perform_ocr(self, image: Image.Image) -> str:
        """
        Perform OCR with optimizations for better text extraction
        
        Args:
            image: PIL Image object
            
        Returns:
            Extracted text string
        """
        try:
            # Try standard OCR first
            text = pytesseract.image_to_string(image, lang='eng')
            
            # If text is very short, try with preprocessing
            if len(text.strip()) < 50:
                logger.info("Short OCR result, trying with preprocessing...")
                preprocessed = self._preprocess_image(image)
                
                # Try with different PSM modes
                configs = [
                    r'--psm 6',  # Assume uniform block of text
                    r'--psm 3',  # Fully automatic page segmentation
                    r'--psm 4',  # Assume single column
                ]
                
                for config in configs:
                    try:
                        alt_text = pytesseract.image_to_string(
                            preprocessed, 
                            lang='eng', 
                            config=config
                        )
                        if len(alt_text) > len(text):
                            text = alt_text
                    except Exception as e:
                        logger.warning(f"OCR with config {config} failed: {e}")
            
            return text
            
        except Exception as e:
            logger.error(f"OCR Error: {e}")
            return ""

    def _extract_with_llm(self, raw_text: str) -> Dict:
        """
        Use Mistral LLM to clean OCR text and extract structured data
        
        Args:
            raw_text: Raw OCR text
            
        Returns:
            Dictionary with extracted fields
        """
        # Create comprehensive prompt with all known issuers
        prompt = f"""
You are an expert certificate data extraction agent. Extract structured information from OCR text of a certificate.

OCR TEXT:
---
{raw_text}
---

EXTRACTION RULES:
1. candidate_name: Extract the full name of the certificate recipient
2. certificate_id: Extract any unique identifier, serial number, or certificate code (e.g., "UC-12345", "ABC123XYZ")
3. issuer_name: Extract ONLY the platform/organization name from this list:
   - Coursera, edX, Udemy, LinkedIn Learning, FutureLearn, Udacity, Alison
   - Great Learning, Simplilearn, Pluralsight, Skillshare, MasterClass, Codecademy
   - freeCodeCamp, SWAYAM, NPTEL, OpenLearn, Khan Academy, upGrad, Shaw Academy
   - Google, Microsoft, IBM, AWS, Meta, Adobe, Apple, Intel, Oracle, SAP, Cisco
   - HubSpot Academy, Salesforce Trailhead, Semrush Academy, DeepLearning.AI
   - PMI, ISACA, (ISC)², Red Hat, VMware, WHO, Linux Foundation, British Council
   - ACCA, CIMA, UNICEF, CompTIA, Palo Alto Networks
   - And any other recognizable educational platform or tech company
   
   IGNORE phrases like: "issued by", "via", "powered by", "in partnership with", "presented by"
   Extract ONLY the primary organization/platform name.

4. issuer_url: Extract the official website URL if present (e.g., coursera.org, udemy.com, edx.org)
   Look for URLs in format: domain.com or www.domain.com or https://domain.com

5. cleaned_text: Provide a cleaned, readable version of the entire certificate text

IMPORTANT:
- Extract ONLY what is clearly visible in the text
- Use null for any field that cannot be determined
- Be precise with issuer_name - match to known platforms
- Certificate IDs often have patterns like "UC-XXXXX", letters+numbers, or alphanumeric codes

Return ONLY valid JSON in this exact format (no markdown, no code blocks):
{{
  "candidate_name": "...",
  "certificate_id": "...",
  "issuer_name": "...",
  "issuer_url": "...",
  "cleaned_text": "..."
}}
"""

        try:
            response = self.client.chat.complete(
                model=self.model,
                messages=[{"role": "user", "content": prompt}]
            )

            cleaned_text = response.choices[0].message.content
            
            # Parse JSON from response
            data = self._parse_json_response(cleaned_text)
            
            return data

        except Exception as e:
            logger.error(f"LLM Extraction Error: {e}")
            return {}

    def _parse_json_response(self, response_text: str) -> Dict:
        """
        Safely parse JSON from LLM response, handling various formats
        
        Args:
            response_text: Raw LLM response
            
        Returns:
            Parsed dictionary
        """
        try:
            # Try direct parsing first
            return json.loads(response_text)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            json_match = re.search(
                r'```(?:json)?\s*(\{.*?\})\s*```', 
                response_text, 
                re.DOTALL
            )
            
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            
            # Try to find any JSON object in the text
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(0))
                except json.JSONDecodeError:
                    pass
        
        # Return empty dict if parsing fails
        logger.warning("Failed to parse JSON from LLM response")
        return {}

    def _normalize_issuer_url(self, url: Optional[str]) -> Optional[str]:
        """
        Normalize issuer URL
        
        Args:
            url: Raw URL from extraction
            
        Returns:
            Normalized URL or None
        """
        if not url:
            return None
        
        url = url.strip()
        
        # Remove common text around URLs
        url = re.sub(r'^.*?(https?://[^\s]+).*$', r'\1', url)
        
        # Add https:// if missing but has domain pattern
        if not url.startswith(('http://', 'https://')):
            if '.' in url and not url.startswith('www.'):
                url = 'https://' + url
            elif url.startswith('www.'):
                url = 'https://' + url
        
        # Remove trailing slash and fragments
        url = url.rstrip('/').split('#')[0].split('?')[0]
        
        return url if url.startswith(('http://', 'https://')) else None

    def _post_process(self, extracted_data: Dict, raw_text: str) -> Dict:
        """
        Post-process extracted data for consistency and quality
        
        Args:
            extracted_data: Data from LLM extraction
            raw_text: Original OCR text
            
        Returns:
            Cleaned and normalized data
        """
        # Ensure all expected keys exist
        default_keys = [
            "candidate_name", 
            "certificate_id", 
            "issuer_name", 
            "issuer_url", 
            "cleaned_text"
        ]
        
        for key in default_keys:
            if key not in extracted_data:
                extracted_data[key] = None

        # Normalize candidate name
        if extracted_data.get("candidate_name"):
            name = extracted_data["candidate_name"]
            # Remove extra whitespace, capitalize properly
            name = ' '.join(name.split())
            # Don't force title case as some names have specific casing
            extracted_data["candidate_name"] = name.strip()

        # Normalize certificate ID
        if extracted_data.get("certificate_id"):
            cert_id = extracted_data["certificate_id"]
            # Remove whitespace
            cert_id = cert_id.strip().replace(' ', '')
            extracted_data["certificate_id"] = cert_id

        # Normalize issuer name (remove common phrases)
        if extracted_data.get("issuer_name"):
            issuer = extracted_data["issuer_name"]
            
            # Remove common unnecessary phrases
            remove_phrases = [
                'issued by', 'provided by', 'powered by', 
                'via', 'through', 'in partnership with',
                'certificate from', 'certification by',
                'in collaboration with', 'presented by'
            ]
            
            issuer_lower = issuer.lower()
            for phrase in remove_phrases:
                issuer_lower = issuer_lower.replace(phrase, '')
            
            # Clean and normalize
            issuer = ' '.join(issuer_lower.split()).strip()
            extracted_data["issuer_name"] = issuer.title() if issuer else None

        # Normalize issuer URL
        if extracted_data.get("issuer_url"):
            extracted_data["issuer_url"] = self._normalize_issuer_url(
                extracted_data["issuer_url"]
            )

        # Add raw text snippet for debugging
        normalized_raw = raw_text.replace('\n', ' ').replace('\r', ' ')
        normalized_raw = re.sub(r'\s+', ' ', normalized_raw)
        extracted_data["raw_text_snippet"] = normalized_raw[:300] + "..." if len(normalized_raw) > 300 else normalized_raw

        # Remove any date fields (as per your original code)
        for date_key in ["certificate_date", "date", "issue_date", "completion_date"]:
            if date_key in extracted_data:
                del extracted_data[date_key]

        return extracted_data

    def extract(self, image_bytes: bytes) -> Dict:
        """
        Extract certificate information from image bytes
        
        Args:
            image_bytes: Raw image data
            
        Returns:
            Dictionary containing:
                - candidate_name: Name of certificate recipient
                - certificate_id: Unique certificate identifier
                - issuer_name: Platform/organization name
                - issuer_url: Official website URL
                - cleaned_text: LLM-cleaned version of OCR text
                - raw_text_snippet: Sample of raw OCR output
        """
        try:
            # Step 1: Load image
            image = Image.open(io.BytesIO(image_bytes))
            
            # Step 2: Perform OCR
            logger.info("Performing OCR extraction...")
            raw_text = self._perform_ocr(image)
            
            if not raw_text.strip():
                logger.warning("OCR returned empty text")
                return {
                    "candidate_name": None,
                    "certificate_id": None,
                    "issuer_name": None,
                    "issuer_url": None,
                    "cleaned_text": None,
                    "raw_text_snippet": "OCR returned no text",
                    "error": "OCR extraction failed - no text found"
                }

            # Step 3: LLM cleanup & extraction
            logger.info("Processing with Mistral LLM...")
            extracted_data = self._extract_with_llm(raw_text)

            # Step 4: Post-processing
            extracted_data = self._post_process(extracted_data, raw_text)

            logger.info(f"Extraction complete: name={extracted_data.get('candidate_name')}, "
                       f"issuer={extracted_data.get('issuer_name')}, "
                       f"cert_id={extracted_data.get('certificate_id')}")

            return extracted_data

        except Exception as e:
            logger.error(f"EXTRACTION ERROR: {e}", exc_info=True)
            return {
                "candidate_name": None,
                "certificate_id": None,
                "issuer_name": None,
                "issuer_url": None,
                "cleaned_text": None,
                "raw_text_snippet": f"Error: {str(e)}",
                "error": str(e)
            }

    def extract_with_fallback(
        self, 
        image_bytes: bytes, 
        fallback_issuer: Optional[str] = None
    ) -> Dict:
        """
        Extract with optional fallback values if extraction fails
        
        Args:
            image_bytes: Raw image data
            fallback_issuer: Fallback issuer name if extraction fails
            
        Returns:
            Extracted data dictionary
        """
        data = self.extract(image_bytes)
        
        # Apply fallbacks if needed
        if not data.get("issuer_name") and fallback_issuer:
            data["issuer_name"] = fallback_issuer
            logger.info(f"Applied fallback issuer: {fallback_issuer}")
        
        return data

    def validate_extraction(self, data: Dict) -> tuple[bool, list[str]]:
        """
        Validate extraction results
        
        Args:
            data: Extracted data dictionary
            
        Returns:
            Tuple of (is_valid, list_of_issues)
        """
        issues = []
        
        if not data.get("candidate_name"):
            issues.append("Missing candidate name")
        
        if not data.get("issuer_name"):
            issues.append("Missing issuer name")
        
        if not data.get("certificate_id"):
            issues.append("Missing certificate ID (may limit verification)")
        
        if not data.get("issuer_url"):
            issues.append("Missing issuer URL (may limit verification)")
        
        if data.get("error"):
            issues.append(f"Extraction error: {data['error']}")
        
        is_valid = len(issues) <= 1  # Allow up to 1 missing field
        
        return is_valid, issues