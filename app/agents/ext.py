import pytesseract
from PIL import Image
import io
import json
import re
from mistralai import Mistral

class ExtractionAgent:

    def __init__(self, api_key: str):
        self.client = Mistral(api_key=api_key)

    def extract(self, image_bytes: bytes) -> dict:
        try:
            # --- OCR STEP ---
            image = Image.open(io.BytesIO(image_bytes))
            raw_text = pytesseract.image_to_string(image, lang='eng')

            # --- PROMPT FOR Mistral ---
            prompt = f"""
You are an OCR cleanup and certificate extraction agent.

OCR TEXT:
---
{raw_text}
---

Return ONLY valid JSON:
{{
  "candidate_name": "...",
  "certificate_id": "...",
  "issuer_name": "Extract only the platform name (e.g., Coursera, Udemy, edX). Ignore phrases like 'issued by', 'via', 'powered by', etc.",
  "issuer_url": "...",
  "cleaned_text": "..."
}}
"""
            response = self.client.chat.complete(
                model="mistral-large-latest",
                messages=[{"role": "user", "content": prompt}]
            )

            cleaned_text = response.choices[0].message.content

            # --- PARSE JSON ---
            try:
                data = json.loads(cleaned_text)
            except:
                json_str = re.search(r"\{.*\}", cleaned_text, re.S)
                data = json.loads(json_str.group(0)) if json_str else {}

            # --- NORMALIZE OCR TEXT ---
            full_text = raw_text.replace('\n', ' ').replace('\r', ' ')
            full_text = re.sub(r'\s+', ' ', full_text)
            
            # Optional: include snippet for logs/UI
            data["raw_text_snippet"] = full_text[:300] + "..."

            # Remove certificate_date entirely
            if "certificate_date" in data:
                del data["certificate_date"]

            return data

        except Exception as e:
            print("EXTRACTION ERROR:", e)
            import traceback
            traceback.print_exc()
            return {
                "candidate_name": None,
                "certificate_id": None,
                "issuer_url": None,
                "cleaned_text": None,
                "raw_text_snippet": f"Error: {str(e)}"
            }
