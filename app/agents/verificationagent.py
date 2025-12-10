"""
verification_agent.py
Core verification agent class for certificate validation
"""

import httpx
import csv
import logging
from urllib.parse import urlparse
from typing import Optional, Tuple, List
from difflib import SequenceMatcher
from datetime import datetime
import re

from app.config import config
from app.schemas import ExtractionResult, VerificationResult

logger = logging.getLogger(__name__)
logger.setLevel(config.LOG_LEVEL)


class VerificationAgent:
    """
    Enhanced verification agent that validates certificates by:
    1. Loading trusted organizations from CSV
    2. Checking domain trust
    3. Crawling verification URLs
    4. Matching candidate names with fuzzy logic
    """
    
    def __init__(self, csv_path: Optional[str] = None, use_playwright: bool = False):
        """
        Initialize the verification agent
        
        Args:
            csv_path: Path to CSV file containing trusted organizations
                     Expected columns: "Organization Name", "Verification URL"
            use_playwright: Whether to use Playwright for JS-heavy pages
        """
        self.csv_path = csv_path or config.CSV_PATH
        self.use_playwright = use_playwright
        self.org_map, self.trusted_domains = self._load_trusted_sources()
        logger.info(f"Loaded {len(self.org_map)} organizations and {len(self.trusted_domains)} trusted domains")

    def _load_trusted_sources(self) -> Tuple[dict, set]:
        """
        Load trusted organizations and their verification URLs from CSV
        
        Returns:
            Tuple of (org_mapping dict, trusted_domains set)
        """
        org_mapping = {}
        trusted_domains = set()
        
        try:
            with open(self.csv_path, mode='r', encoding='utf-8-sig') as file:
                reader = csv.DictReader(file)
                
                # Strip whitespace from headers
                reader.fieldnames = [name.strip() for name in reader.fieldnames]
                
                for row in reader:
                    org_name = row.get("Organization Name", "").strip()
                    verify_url = row.get("Verification URL", "").strip()
                    
                    if verify_url:
                        # Normalize URL
                        if not verify_url.startswith(('http://', 'https://')):
                            verify_url = 'https://' + verify_url
                        
                        # Extract domain for trust checking
                        parsed = urlparse(verify_url)
                        domain = parsed.netloc.lower().replace("www.", "")
                        trusted_domains.add(domain)
                        
                        # Map organization name to verification base URL
                        if org_name:
                            org_mapping[org_name.lower()] = verify_url
                
                logger.info(f"Successfully loaded {len(org_mapping)} organizations from CSV")
                
        except FileNotFoundError:
            logger.error(f"CSV file not found: {self.csv_path}")
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
        
        # Add common fallback domains if needed
        if not trusted_domains:
            logger.warning("No trusted domains loaded, adding fallback")
            trusted_domains.add("udemy.com")
            trusted_domains.add("coursera.org")
        
        return org_mapping, trusted_domains

    def _is_trusted_domain(self, url: str) -> bool:
        """
        Check if URL belongs to a trusted domain
        
        Args:
            url: URL to check
            
        Returns:
            True if domain is trusted, False otherwise
        """
        try:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().replace("www.", "")
            
            # Check exact match
            if domain in self.trusted_domains:
                return True
            
            # Check if any trusted domain is a suffix (for subdomains)
            for trusted in self.trusted_domains:
                if domain.endswith(f".{trusted}") or domain == trusted:
                    return True
            
            return False
        except Exception as e:
            logger.error(f"Error checking domain trust: {e}")
            return False

    def _normalize_url(self, url: str, cert_id: Optional[str] = None) -> str:
        """
        Normalize and construct full verification URL
        
        Args:
            url: Base URL or partial URL
            cert_id: Certificate ID to append if needed
            
        Returns:
            Normalized full URL
        """
        if not url:
            return ""
        
        # Add https if missing
        if not url.startswith(('http://', 'https://')):
            url = 'https://' + url
        
        # Append certificate ID if provided and not already in URL
        if cert_id and cert_id not in url:
            if not url.endswith('/'):
                url += '/'
            url += cert_id
        
        return url

    def _fuzzy_match_name(self, name1: str, name2: str, threshold: float = 0.75) -> Tuple[bool, float]:
        """
        Perform fuzzy matching between two names
        
        Args:
            name1: First name (from certificate)
            name2: Second name or text content
            threshold: Minimum similarity ratio (0.0 to 1.0)
            
        Returns:
            Tuple of (is_match bool, similarity_score float)
        """
        if not name1 or not name2:
            return False, 0.0
        
        # Normalize names
        name1_clean = re.sub(r'[^a-z0-9\s]', '', name1.lower())
        name2_clean = re.sub(r'[^a-z0-9\s]', '', name2.lower())
        
        # Check if name1 is contained in name2 (exact substring match)
        if name1_clean in name2_clean:
            return True, 1.0
        
        # Split into parts and check individual components
        name1_parts = [part for part in name1_clean.split() if len(part) > 2]
        
        if not name1_parts:
            return False, 0.0
        
        # Check if all significant parts are present
        all_parts_present = all(part in name2_clean for part in name1_parts)
        
        if all_parts_present:
            return True, 0.95
        
        # Fuzzy matching as fallback
        ratio = SequenceMatcher(None, name1_clean, name2_clean).ratio()
        
        return ratio >= threshold, ratio

    async def _fetch_page_content_httpx(self, url: str) -> Optional[str]:
        """
        Fetch page content using httpx (fast, for static pages)
        
        Args:
            url: URL to fetch
            
        Returns:
            Page text content or None if failed
        """
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        
        try:
            async with httpx.AsyncClient(
                timeout=15.0, 
                follow_redirects=True,
                verify=True
            ) as client:
                # Add cache-busting parameter
                params = {"_t": str(int(datetime.now().timestamp()))}
                response = await client.get(url, headers=headers, params=params)
                
                if response.status_code == 200:
                    return response.text
                else:
                    logger.warning(f"HTTP {response.status_code} for URL: {url}")
                    return None
                    
        except httpx.TimeoutException:
            logger.error(f"Timeout fetching URL: {url}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error for URL {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching URL {url}: {e}")
            return None

    async def _fetch_page_content_playwright(self, url: str) -> Optional[str]:
        """
        Fetch page content using Playwright (for JS-heavy pages)
        
        Args:
            url: URL to fetch
            
        Returns:
            Page text content or None if failed
        """
        try:
            from playwright.async_api import async_playwright
            
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                )
                page = await context.new_page()
                
                # Navigate and wait for content
                await page.goto(url, timeout=15000, wait_until='networkidle')
                
                # Get text content
                text_content = await page.inner_text("body")
                
                await browser.close()
                
                return text_content
                
        except ImportError:
            logger.error("Playwright not installed. Install with: pip install playwright && playwright install")
            return None
        except Exception as e:
            logger.error(f"Playwright error for URL {url}: {e}")
            return None

    async def _fetch_page_content(self, url: str) -> Optional[str]:
        """
        Fetch page content using the configured method
        
        Args:
            url: URL to fetch
            
        Returns:
            Page text content or None if failed
        """
        if self.use_playwright:
            logger.info(f"Fetching with Playwright: {url}")
            content = await self._fetch_page_content_playwright(url)
            
            # Fallback to httpx if Playwright fails
            if not content:
                logger.info("Playwright failed, falling back to httpx")
                content = await self._fetch_page_content_httpx(url)
            
            return content
        else:
            logger.info(f"Fetching with httpx: {url}")
            content = await self._fetch_page_content_httpx(url)
            
            # If httpx returns suspiciously short content, try Playwright
            if content and len(content) < 500 and "javascript" in content.lower():
                logger.info("Detected JS-heavy page, trying Playwright")
                playwright_content = await self._fetch_page_content_playwright(url)
                if playwright_content and len(playwright_content) > len(content):
                    return playwright_content
            
            return content

    async def verify(self, extraction_data: ExtractionResult) -> VerificationResult:
        """
        Main verification method
        
        Args:
            extraction_data: Extracted certificate data
            
        Returns:
            VerificationResult with verification status and details
        """
        url = extraction_data.issuer_url
        cert_id = extraction_data.certificate_id
        org_name = extraction_data.issuer_name.value if extraction_data.issuer_name else None
        candidate_name = extraction_data.candidate_name
        
        logger.info(f"Starting verification for candidate: {candidate_name}, org: {org_name}")
        
        # Step 1: Reconstruct URL if missing
        if not url and org_name and cert_id:
            base_url = self.org_map.get(org_name.lower())
            if base_url:
                url = self._normalize_url(base_url, cert_id)
                logger.info(f"Reconstructed URL: {url}")
            else:
                return VerificationResult(
                    is_verified=False,
                    message=f"Organization '{org_name}' not found in trusted list.",
                    trusted_domain=False
                )
        
        if not url:
            return VerificationResult(
                is_verified=False,
                message="No URL available for verification. Missing both issuer_url and organization mapping.",
                trusted_domain=False
            )
        
        # Step 2: Normalize URL
        url = self._normalize_url(url, cert_id)
        
        # Step 3: Check domain trust
        is_trusted = self._is_trusted_domain(url)
        
        if not is_trusted:
            logger.warning(f"Untrusted domain: {url}")
            return VerificationResult(
                is_verified=False,
                message=f"Domain is not in the trusted list. URL: {url}",
                trusted_domain=False
            )
        
        # Step 4: Fetch page content
        page_content = await self._fetch_page_content(url)
        
        if not page_content:
            return VerificationResult(
                is_verified=False,
                message=f"Failed to fetch content from URL: {url}",
                trusted_domain=True
            )
        
        # Step 5: Verify candidate name
        if not candidate_name:
            return VerificationResult(
                is_verified=False,
                message="No candidate name provided for verification.",
                trusted_domain=True
            )
        
        is_match, similarity = self._fuzzy_match_name(candidate_name, page_content)
        
        if is_match:
            logger.info(f"✓ Verification successful for {candidate_name} (similarity: {similarity:.2f})")
            return VerificationResult(
                is_verified=True,
                message=f"Verified successfully. Name match confidence: {similarity:.2%}",
                trusted_domain=True
            )
        else:
            logger.warning(f"✗ Name mismatch for {candidate_name} (similarity: {similarity:.2f})")
            return VerificationResult(
                is_verified=False,
                message=f"Name mismatch. Similarity: {similarity:.2%}. Expected: '{candidate_name}'",
                trusted_domain=True
            )

    def add_trusted_domain(self, domain: str):
        """Manually add a trusted domain"""
        self.trusted_domains.add(domain.lower().replace("www.", ""))
        logger.info(f"Added trusted domain: {domain}")

    def add_organization(self, org_name: str, verification_url: str):
        """Manually add an organization mapping"""
        self.org_map[org_name.lower()] = verification_url
        parsed = urlparse(verification_url)
        domain = parsed.netloc.lower().replace("www.", "")
        self.trusted_domains.add(domain)
        logger.info(f"Added organization: {org_name} -> {verification_url}")