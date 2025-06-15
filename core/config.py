import os
from typing import Optional


class Settings:
    """Application settings and configuration"""

    def __init__(self):
        self.SESSDATA: Optional[str] = os.getenv("SESSDATA")
        self.BILI_JCT: Optional[str] = os.getenv("BILI_JCT")
        self.UP_MID: Optional[str] = os.getenv("UP_MID")

        # API settings
        self.REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "10"))
        self.DEFAULT_PAGE_SIZE: int = int(os.getenv("DEFAULT_PAGE_SIZE", "20"))
        self.MAX_PAGE_SIZE: int = int(os.getenv("MAX_PAGE_SIZE", "50"))

        # Headers for requests
        self.HEADERS = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://www.bilibili.com",
        }

        # Build cookie header
        self._build_cookie_header()

    def _build_cookie_header(self):
        """Build cookie header from environment variables"""
        cookie_parts = []
        if self.SESSDATA:
            cookie_parts.append(f"SESSDATA={self.SESSDATA}")
        if self.BILI_JCT:
            cookie_parts.append(f"BILI_JCT={self.BILI_JCT}")

        if cookie_parts:
            self.HEADERS["Cookie"] = "; ".join(cookie_parts)

    def is_configured(self) -> bool:
        """Check if required configuration is present"""
        return bool(self.SESSDATA and self.UP_MID)

    def get_missing_config(self) -> list[str]:
        """Get list of missing required configuration"""
        missing = []
        if not self.SESSDATA:
            missing.append("SESSDATA")
        if not self.UP_MID:
            missing.append("UP_MID")
        return missing


# Global settings instance
settings = Settings()
