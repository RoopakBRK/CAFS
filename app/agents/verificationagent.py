"""
Enhanced Verification Agent with improved verification logic
Integrates seamlessly with your existing FastAPI setup
"""

import httpx
import csv
import logging
from urllib.parse import urlparse, urljoin
from typing import Optional, Tuple, List, Dict
from difflib import SequenceMatcher
from datetime import datetime
import re
import asyncio

from app.config import config
from app.schemas import ExtractionResult, VerificationResult

logger = logging.getLogger(__name__)
logger.setLevel(config.LOG_LEVEL)


class VerificationAgent:
    """
    Enhanced verification agent that validates certificates by:
    1. Loading trusted organizations from CSV
    2. Checking domain trust
    3. Crawling verification URLs with multiple strategies
    4. Matching candidate names with fuzzy logic
    5. Attempting multiple URL patterns for common platforms
    """
    
    # Common verification URL patterns for major platforms
    URL_PATTERNS = {
        "coursera": [
            "https://www.coursera.org/verify/{cert_id}",
            "https://www.coursera.org/account/accomplishments/certificate/{cert_id}",
            "https://coursera.org/verify/{cert_id}"
        ],
        "udemy": [
            "https://www.udemy.com/certificate/{cert_id}",
            "https://udemy.com/certificate/UC-{cert_id}"
        ],
        "edx": [
            "https://credentials.edx.org/credentials/{cert_id}",
            "https://courses.edx.org/certificates/{cert_id}"
        ],
        "linkedin learning": [
            "https://www.linkedin.com/learning/certificates/{cert_id}"
        ],
        "google": [
            "https://www.credential.net/{cert_id}",
            "https://google.accredible.com/{cert_id}"
        ],
        "microsoft": [
            "https://www.credly.com/badges/{cert_id}",
            "https://learn.microsoft.com/api/credentials/share/{cert_id}"
        ],
        "ibm": [
            "https://www.credly.com/badges/{cert_id}",
            "https://www.youracclaim.com/badges/{cert_id}"
        ],
        "aws": [
            "https://www.credly.com/badges/{cert_id}",
            "https://aw.certmetrics.com/amazon/public/verification.aspx?code={cert_id}"
        ]
    }
    
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
        self.session_cache: Dict[str, str] = {}  # Cache for fetched pages
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
                            org_key = org_name.lower().strip()
                            org_mapping[org_key] = verify_url
                
                logger.info(f"Successfully loaded {len(org_mapping)} organizations from CSV")
                
        except FileNotFoundError:
            logger.error(f"CSV file not found: {self.csv_path}")
        except Exception as e:
            logger.error(f"Error loading CSV: {e}")
        
        # Add common fallback domains
        fallback_domains = [
            "udemy.com", "coursera.org", "edx.org", "linkedin.com",
            "credential.net", "credly.com", "youracclaim.com",
            "accredible.com", "certmetrics.com"
        ]
        
        for domain in fallback_domains:
            trusted_domains.add(domain)
        
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

    def _get_url_patterns_for_issuer(self, issuer_name: str, cert_id: str) -> List[str]:
        """
        Get possible URL patterns for a given issuer
        
        Args:
            issuer_name: Name of the issuing organization
            cert_id: Certificate ID
            
        Returns:
            List of possible verification URLs
        """
        if not cert_id:
            return []
        
        issuer_lower = issuer_name.lower().strip()
        urls = []
        
        # Check if we have predefined patterns
        for key, patterns in self.URL_PATTERNS.items():
            if key in issuer_lower or issuer_lower in key:
                for pattern in patterns:
                    try:
                        url = pattern.format(cert_id=cert_id)
                        urls.append(url)
                    except Exception as e:
                        logger.warning(f"Error formatting URL pattern: {e}")
        
        # Check CSV mapping
        if issuer_lower in self.org_map:
            base_url = self.org_map[issuer_lower]
            urls.append(self._normalize_url(base_url, cert_id))
        
        return urls

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
            # Handle different URL structures
            if url.endswith('/'):
                url += cert_id
            elif '?' in url:
                url += f"&id={cert_id}"
            else:
                url += f"/{cert_id}"
        
        return url

    def _fuzzy_match_name(self, name1: str, name2: str, threshold: float = 0.70) -> Tuple[bool, float]:
        """
        Perform fuzzy matching between two names with improved logic
        
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
            # If name is too short, require exact match
            ratio = SequenceMatcher(None, name1_clean, name2_clean).ratio()
            return ratio >= 0.9, ratio
        
        # Check if all significant parts are present
        parts_found = sum(1 for part in name1_parts if part in name2_clean)
        if parts_found == len(name1_parts):
            return True, 0.95
        
        # Partial match - check if at least half the parts are present
        if parts_found >= len(name1_parts) / 2:
            partial_score = 0.7 + (0.2 * parts_found / len(name1_parts))
            return partial_score >= threshold, partial_score
        
        # Fuzzy matching as fallback
        ratio = SequenceMatcher(None, name1_clean, name2_clean).ratio()
        
        # Also check for reversed names (e.g., "John Doe" vs "Doe John")
        name1_reversed = ' '.join(reversed(name1_parts))
        ratio_reversed = SequenceMatcher(None, name1_reversed, name2_clean).ratio()
        
        best_ratio = max(ratio, ratio_reversed)
        
        return best_ratio >= threshold, best_ratio

    async def _fetch_page_content_httpx(self, url: str, use_cache: bool = True) -> Optional[str]:
        """
        Fetch page content using httpx (fast, for static pages)
        
        Args:
            url: URL to fetch
            use_cache: Whether to use cached content
            
        Returns:
            Page text content or None if failed
        """
        # Check cache
        if use_cache and url in self.session_cache:
            logger.info(f"Using cached content for: {url}")
            return self.session_cache[url]
        
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
                    content = response.text
                    # Cache the content
                    if use_cache:
                        self.session_cache[url] = content
                    return content
                elif response.status_code == 404:
                    logger.warning(f"HTTP 404 (Not Found) for URL: {url}")
                    return None
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
                await page.goto(url, timeout=20000, wait_until='networkidle')
                
                # Wait a bit for any dynamic content
                await asyncio.sleep(2)
                
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
        Fetch page content using the configured method with smart fallback
        
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
            if content and len(content) < 500 and any(
                keyword in content.lower() 
                for keyword in ["javascript", "noscript", "loading", "please enable"]
            ):
                logger.info("Detected JS-heavy page, trying Playwright")
                playwright_content = await self._fetch_page_content_playwright(url)
                if playwright_content and len(playwright_content) > len(content):
                    return playwright_content
            
            return content

    async def _try_multiple_urls(
        self, 
        urls: List[str], 
        candidate_name: str
    ) -> Tuple[bool, float, Optional[str]]:
        """
        Try multiple URLs and return best match
        
        Args:
            urls: List of URLs to try
            candidate_name: Name to verify
            
        Returns:
            Tuple of (is_verified, best_similarity, successful_url)
        """
        best_similarity = 0.0
        best_url = None
        
        for url in urls:
            logger.info(f"Trying URL: {url}")
            
            content = await self._fetch_page_content(url)
            
            if content:
                is_match, similarity = self._fuzzy_match_name(candidate_name, content)
                
                if similarity > best_similarity:
                    best_similarity = similarity
                    best_url = url
                
                if is_match:
                    logger.info(f"✓ Match found at {url} (similarity: {similarity:.2f})")
                    return True, similarity, url
            
            # Small delay between requests
            await asyncio.sleep(0.5)
        
        return False, best_similarity, best_url

    async def verify(self, extraction_data: ExtractionResult) -> VerificationResult:
        """
        Main verification method with enhanced URL pattern matching
        
        Args:
            extraction_data: Extracted certificate data
            
        Returns:
            VerificationResult with verification status and details
        """
        url = extraction_data.issuer_url
        cert_id = extraction_data.certificate_id
        org_name = extraction_data.issuer_name.value if extraction_data.issuer_name else None
        candidate_name = extraction_data.candidate_name
        
        logger.info(f"Starting verification for candidate: {candidate_name}, org: {org_name}, cert_id: {cert_id}")
        
        # Validate candidate name
        if not candidate_name:
            return VerificationResult(
                is_verified=False,
                message="No candidate name provided for verification.",
                trusted_domain=False
            )
        
        # Build list of URLs to try
        urls_to_try = []
        
        # Step 1: Add provided URL if available
        if url:
            normalized_url = self._normalize_url(url, cert_id)
            urls_to_try.append(normalized_url)
        
        # Step 2: Add pattern-based URLs if we have org name and cert ID
        if org_name and cert_id:
            pattern_urls = self._get_url_patterns_for_issuer(org_name, cert_id)
            urls_to_try.extend(pattern_urls)
        
        # Step 3: If still no URLs, try CSV mapping
        if not urls_to_try and org_name:
            org_lower = org_name.lower().strip()
            if org_lower in self.org_map:
                base_url = self.org_map[org_lower]
                urls_to_try.append(self._normalize_url(base_url, cert_id))
        
        # Remove duplicates while preserving order
        urls_to_try = list(dict.fromkeys(urls_to_try))
        
        if not urls_to_try:
            return VerificationResult(
                is_verified=False,
                message=f"No verification URL available for organization '{org_name}'.",
                trusted_domain=False
            )
        
        logger.info(f"Will try {len(urls_to_try)} URL(s)")
        
        # Step 4: Check if any URL is from trusted domain
        has_trusted_url = any(self._is_trusted_domain(u) for u in urls_to_try)
        
        if not has_trusted_url:
            return VerificationResult(
                is_verified=False,
                message=f"None of the verification URLs are from trusted domains.",
                trusted_domain=False
            )
        
        # Step 5: Try URLs and verify name
        is_verified, similarity, successful_url = await self._try_multiple_urls(
            urls_to_try, 
            candidate_name
        )
        
        if is_verified:
            logger.info(f"✓ Verification successful for {candidate_name} (similarity: {similarity:.2f})")
            return VerificationResult(
                is_verified=True,
                message=f"Verified successfully at {successful_url}. Name match confidence: {similarity:.2%}",
                trusted_domain=True
            )
        elif similarity > 0:
            logger.warning(f"✗ Name mismatch for {candidate_name} (best similarity: {similarity:.2f})")
            return VerificationResult(
                is_verified=False,
                message=f"Name mismatch. Best similarity: {similarity:.2%}. Expected: '{candidate_name}'. Checked {len(urls_to_try)} URL(s).",
                trusted_domain=True
            )
        else:
            return VerificationResult(
                is_verified=False,
                message=f"Failed to fetch content from any of the {len(urls_to_try)} verification URL(s).",
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
    
    def clear_cache(self):
        """Clear the page content cache"""
        self.session_cache.clear()
        logger.info("Cache cleared")