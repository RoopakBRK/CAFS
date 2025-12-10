import pytesseract
from PIL import Image
import io
import re
import csv
import logging
from typing import Optional, Dict, Any, List
from app.config import config
from app.schemas import ExtractionResult

logger = logging.getLogger(__name__)
logger.setLevel(config.LOG_LEVEL)

class ExtractionAgent:

    def __init__(self):
        # Load known organizations for detection
        self.known_orgs = self._load_org_list(config.CSV_PATH)

    def _load_org_list(self, csv_path):
        """
        Loads just the list of organization names for matching.
        """
        orgs = []
        try:
            with open(csv_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    name = row.get("Organization Name", "").strip()
                    if name:
                        orgs.append(name)
            return orgs
        except FileNotFoundError:
            return ["Coursera", "Udemy", "edX", "LinkedIn", "IBM", "Google", "Udacity"]

    def extract(self, image_bytes: bytes) -> ExtractionResult:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            raw_text = pytesseract.image_to_string(image, lang='eng')
            
            # 1. Basic Extraction
            name = self._find_candidate_name(raw_text)
            if not name:
                name = self._fallback_name_search(raw_text)

            # 2. Extract Specific Details
            cert_id = self._find_certificate_id(raw_text)
            
            # 3. Identify the Organization
            issuer_org = self._identify_organization(raw_text)

            # 4. Find/Repair URL (Standard method)
            raw_url = self._find_url(raw_text)
            clean_url = self._repair_url(raw_url) if raw_url else None

            return ExtractionResult(
                candidate_name=name,
                certificate_id=cert_id,
                issuer_url=clean_url,
                issuer_org=issuer_org,
                raw_text_snippet=raw_text[:300].replace("\n", " ") + "..."
            )

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            return ExtractionResult(
                candidate_name=None, 
                certificate_id=None, 
                issuer_url=None,
                raw_text_snippet=f"Error: {str(e)}"
            )

    def _identify_organization(self, text: str) -> str:
        """
        Scans the text for known organization names from the CSV.
        """
        text_lower = text.lower()
        
        # Priority Check: Look for major platforms first to avoid confusion
        # (e.g., An IBM cert might mention 'Coursera', we want 'Coursera' if that's the platform)
        priority_platforms = ['coursera', 'udemy', 'edx', 'udacity', 'futurelearn']
        for platform in priority_platforms:
            if platform in text_lower:
                return platform.capitalize() # Normalize return value

        # Secondary Check: Look for any org in the CSV
        for org in self.known_orgs:
            if org.lower() in text_lower:
                return org
        
        return None

    def _find_certificate_id(self, text: str):
        # Improved Regex to avoid capturing words like "Certificate"
        
        # 1. Udemy Pattern (Strongest)
        udemy_match = re.search(r'(UC-[a-zA-Z0-9-]+)', text)
        if udemy_match: return udemy_match.group(1)

        # 2. Label-based search (looks for "ID: XXXXX")
        # [:\s#]+ matches colons, spaces, or hashes
        # ([a-z0-9]{8,40}) captures ONLY alphanumeric strings between 8-40 chars.
        # This prevents capturing "Certificate" (which has no numbers)
        id_pattern = r'(?i)(?:id|number|no\.?|code|credential)[:\s#]+([a-z0-9]*\d[a-z0-9]*)' 
        match = re.search(id_pattern, text)
        if match:
            found_id = match.group(1)
            # Integrity check: Ensure it's not a common word and has length
            if len(found_id) > 5 and found_id.lower() != "certificate":
                return found_id

        # 3. Fallback: Look for lone long alphanumeric hashes (common in edX/IBM)
        # Must be 10-35 chars, mixing letters and numbers
        hash_match = re.search(r'\b(?=[a-z0-9]*\d)(?=[a-z0-9]*[a-z])[a-z0-9]{10,35}\b', text.lower())
        if hash_match:
            return hash_match.group(0)

        return None

    def _find_url(self, text: str):
        url_pattern = r'(?:https?://|www\.|ude\.my/|coursera\.org/)[^\s]+'
        matches = re.findall(url_pattern, text)
        if matches:
            return matches[0].rstrip('.,])')
        return None

    def _repair_url(self, url: str) -> str:
        if not url: return None
        if "ude.my/" in url:
            parts = url.split("ude.my/")
            if len(parts) > 1:
                return parts[0] + "ude.my/" + parts[1].replace('l', '1').replace('O', '0')
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        return url

    def _find_candidate_name(self, text: str):
        # (Same Logic as before - kept concise for brevity)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        triggers_after = ["successfully completed", "has completed", "for successfully completing"]
        triggers_before = ["this is to certify that", "presented to", "awarded to", "certifies that"]

        for i, line in enumerate(lines):
            line_lower = line.lower()
            for trigger in triggers_after:
                if trigger in line_lower:
                    if line_lower.startswith(trigger) and i > 0: return self._clean_name(lines[i-1])
                    return self._clean_name(line_lower.split(trigger)[0])
            for trigger in triggers_before:
                if trigger in line_lower:
                    parts = line.split(trigger)
                    if len(parts) > 1 and len(parts[1].strip()) > 3: return self._clean_name(parts[1])
                    if i + 1 < len(lines): return self._clean_name(lines[i+1])
        return None

    def _fallback_name_search(self, text: str):
        # (Same Logic as before)
        lines = [line.strip() for line in text.split('\n') if line.strip()]
        blacklist = ["certificate", "completion", "id:", "url:", "course", "udemy", "coursera", "verify", "ibm", "edx", "google"]
        possible_names = []
        for line in lines:
            if not any(word in line.lower() for word in blacklist) and 4 < len(line) < 50 and not re.search(r'\d', line):
                possible_names.append(line)
        return possible_names[0] if possible_names else None

    def _clean_name(self, name_str: str):
        name_str = re.sub(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4}', '', name_str, flags=re.IGNORECASE)
        name_str = re.sub(r'[^a-zA-Z\s\.]+$', '', name_str)
        return name_str.strip().title()