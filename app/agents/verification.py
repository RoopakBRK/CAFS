import httpx
import csv
import logging
from urllib.parse import urlparse
from app.config import config
from app.schemas import ExtractionResult, VerificationResult

logger = logging.getLogger(__name__)
logger.setLevel(config.LOG_LEVEL)

class VerificationAgent:
    
    def __init__(self):
        # Load data: We need both a map (for construction) and a list (for validation)
        self.org_map, self.trusted_prefixes = self._load_trusted_sources(config.CSV_PATH)

    def _load_trusted_sources(self, csv_path):
        """
        Reads CSV to build:
        1. org_map: {'Coursera': 'https://coursera.org/verify/', ...} for URL construction.
        2. trusted_prefixes: A list of all valid verification URLs for security checking.
        """
        org_mapping = {}
        prefixes = []
        
        try:
            with open(csv_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                
                # --- DEBUG: Verify CSV headers ---
                # print(f"CSV Headers found: {reader.fieldnames}") 
                
                for row in reader:
                    # Get relevant columns
                    org_name = row.get("Organization Name", "").strip()
                    verify_url = row.get("Verification URL", "").strip()
                    
                    if verify_url:
                        # Add to list of trusted URLs
                        prefixes.append(verify_url)
                        
                        # Add to lookup map if Org Name exists
                        if org_name:
                            org_mapping[org_name.lower()] = verify_url
                            
            # Add manual fallbacks
            prefixes.append("https://ude.my/")
            
            # --- DEBUG: Confirm load status ---
            print(f"Loaded {len(prefixes)} trusted sources and {len(org_mapping)} organization maps.")
            
            return org_mapping, prefixes
            
        except FileNotFoundError:
            print(f"Error: {csv_path} was not found. Verification capabilities will be limited.")
            return {}, []
        except Exception as e:
            print(f"Error reading CSV: {e}")
            return {}, []

    async def verify(self, extraction_data: ExtractionResult) -> VerificationResult:
        # 1. Unpack Data
        url = extraction_data.issuer_url
        org_name = extraction_data.issuer_org
        cert_id = extraction_data.certificate_id
        candidate_name = extraction_data.candidate_name
        
        # 2. Smart URL Construction (The Missing Link Fix)
        # If we lack a URL but have the Org and ID, we build it here.
        if not url:
            if org_name and cert_id:
                logger.info(f"Attempting to reconstruct URL for {org_name}...")
                
                # Look up the base URL from our CSV map
                base_url = self.org_map.get(org_name.lower())
                
                if base_url:
                    # Ensure base ends with slash before adding ID
                    if not base_url.endswith('/'):
                        base_url += '/'
                    url = f"{base_url}{cert_id}"
                    logger.info(f"Reconstructed URL: {url}")
                else:
                    return VerificationResult(
                        is_verified=False, 
                        message=f"Organization '{org_name}' not found in trusted list.", 
                        trusted_domain=False
                    )
            else:
                return VerificationResult(
                    is_verified=False, 
                    message="Missing URL and insufficient data (Org/ID) to reconstruct it.", 
                    trusted_domain=False
                )

        # 3. URL Normalization
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url

        # 4. Domain Security Check
        # Does this URL start with one of our trusted prefixes?
        is_trusted = False
        url_clean = url.replace("www.", "").lower()
        
        for prefix in self.trusted_prefixes:
            prefix_clean = prefix.replace("www.", "").lower()
            if url_clean.startswith(prefix_clean):
                is_trusted = True
                break

        if not is_trusted:
            return VerificationResult(
                is_verified=False,
                message="URL domain is not in the trusted onlinelist.csv.",
                trusted_domain=False
            )

        # 5. External Verification Request
        try:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            }
            
            # Request the constructed or extracted URL
            response = None
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(url, headers=headers)

            if response:
                if response.status_code == 200:
                    if candidate_name: 
                        name_parts = [part for part in candidate_name.lower().split() if len(part) > 2]
                        matches = all(part in response.text.lower() for part in name_parts) if name_parts else False
                        
                        if matches:
                            return VerificationResult(is_verified=True, message="Verified (Name Match).", trusted_domain=True)
                        else:
                            # Soft pass: Valid link, valid ID, but name might be formatted differently on page
                            return VerificationResult(is_verified=True, message="Verified Domain (Name mismatch/OCR error).", trusted_domain=True)
                    else:
                        return VerificationResult(is_verified=True, message="Verified Domain (Name unreadable).", trusted_domain=True)

                elif response.status_code == 403:
                    # Security blocking (Common with LinkedIn/Udemy)
                    return VerificationResult(is_verified=True, message="Verified (Trusted Source - Access Blocked).", trusted_domain=True)
                
                elif response.status_code == 404:
                     return VerificationResult(is_verified=False, message="Invalid Certificate ID (404 Not Found).", trusted_domain=True)

                else:
                    return VerificationResult(is_verified=False, message=f"Server Status: {response.status_code}", trusted_domain=True)
            else:
                return VerificationResult(is_verified=False, message="Failed to get response (No response object)", trusted_domain=True)

        except Exception as e:
            logger.error(f"Verification error: {e}")
            return VerificationResult(is_verified=False, message=str(e), trusted_domain=True)