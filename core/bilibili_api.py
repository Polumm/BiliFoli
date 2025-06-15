import httpx
import json
from typing import Dict, Any, Optional, List
from .config import settings


class BilibiliAPI:
    """Bilibili API client for favorite folders and videos"""

    def __init__(self):
        self.base_url = "https://api.bilibili.com"
        self.client = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client"""
        if self.client is None:
            self.client = httpx.AsyncClient(
                headers=settings.HEADERS, timeout=settings.REQUEST_TIMEOUT
            )
        return self.client

    def check_config(self) -> Optional[str]:
        """Check if required configuration is present"""
        if not settings.is_configured():
            missing = settings.get_missing_config()
            missing_vars = ", ".join(missing)
            return f"Missing required environment variables: {missing_vars}. Please set them in your environment."
        return None

    async def get_favorite_folders(self) -> Dict[str, Any]:
        """Get list of favorite folders"""
        try:
            client = await self._get_client()

            response = await client.get(
                f"{self.base_url}/x/v3/fav/folder/created/list-all",
                params={"up_mid": settings.UP_MID},
            )
            response.raise_for_status()

            data = response.json()

            # Check Bilibili API response code
            if data.get("code") != 0:
                error_message = data.get(
                    "message", "Unknown Bilibili API error"
                )
                return {
                    "success": False,
                    "error": f"Bilibili API Error: {error_message} (Code: {data.get('code')}). This often means your SESSDATA or UP_MID is invalid/expired.",
                }

            # Validate response structure
            if "data" not in data or "list" not in data["data"]:
                return {
                    "success": False,
                    "error": "Unexpected API response structure. The API might have changed or your credentials are invalid.",
                }

            folders = data["data"]["list"]

            return {"success": True, "data": folders}

        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Network error: {str(e)}. Please check your internet connection.",
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP error {e.response.status_code}: {e.response.text}. This could mean your credentials are invalid or there's a server issue.",
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON response from Bilibili API. This often happens when credentials are invalid and an HTML error page is returned instead of JSON.",
            }
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    async def get_folder_videos(
        self, media_id: int, page: int = 1, page_size: int = 20
    ) -> Dict[str, Any]:
        """Get videos in a specific folder with pagination"""
        try:
            client = await self._get_client()

            # Ensure page_size is within limits
            page_size = min(page_size, settings.MAX_PAGE_SIZE)
            page_size = max(page_size, 1)

            response = await client.get(
                f"{self.base_url}/x/v3/fav/resource/list",
                params={
                    "up_mid": settings.UP_MID,
                    "media_id": media_id,
                    "ps": page_size,  # page size
                    "pn": page,  # page number
                    "platform": "web",
                },
            )
            response.raise_for_status()

            data = response.json()

            # Check Bilibili API response code
            if data.get("code") != 0:
                error_message = data.get(
                    "message", "Unknown Bilibili API error"
                )
                return {
                    "success": False,
                    "error": f"Bilibili API Error: {error_message} (Code: {data.get('code')}). This might mean the folder ID is incorrect or your credentials are invalid.",
                }

            # Validate response structure
            if "data" not in data:
                return {
                    "success": False,
                    "error": "Unexpected API response structure. The API might have changed or your credentials are invalid.",
                }

            response_data = data["data"]
            folder_info = response_data.get(
                "info", {"title": "Unknown Folder"}
            )
            videos = response_data.get("medias", [])
            has_more = response_data.get("has_more", False)

            # Process video data
            processed_videos = []
            for video in videos:
                if video:  # Skip None entries
                    processed_video = {
                        "id": video.get("id"),
                        "title": video.get("title", "Untitled Video"),
                        "cover": video.get(
                            "cover", "https://i.ibb.co/C03gqfS/no-image.png"
                        ),
                        "bvid": video.get("bvid"),
                        "duration": video.get("duration", 0),
                        "pubtime": video.get("pubtime", 0),
                        "upper": video.get("upper", {}),
                        "cnt_info": video.get("cnt_info", {}),
                        "intro": video.get("intro", ""),
                    }
                    processed_videos.append(processed_video)

            return {
                "success": True,
                "data": {
                    "info": folder_info,
                    "videos": processed_videos,
                    "has_more": has_more,
                    "current_page": page,
                    "page_size": page_size,
                },
            }

        except httpx.RequestError as e:
            return {
                "success": False,
                "error": f"Network error: {str(e)}. Please check your internet connection.",
            }
        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"HTTP error {e.response.status_code}: {e.response.text}. This could mean the folder ID is incorrect, your credentials are invalid, or there's a server issue.",
            }
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "error": f"Invalid JSON response from Bilibili API. This often happens when credentials are invalid and an HTML error page is returned instead of JSON.",
            }
        except Exception as e:
            return {"success": False, "error": f"Unexpected error: {str(e)}"}

    async def close(self):
        """Close the HTTP client"""
        if self.client:
            await self.client.aclose()
            self.client = None
            
    
    async def get_cid(self, bvid: str) -> Optional[int]:
        client = await self._get_client()
        resp = await client.get(
            f"{self.base_url}/x/web-interface/view",
            params={"bvid": bvid}
        )
        resp.raise_for_status()
        j = resp.json()
        if j.get("code") != 0 or "data" not in j or "cid" not in j["data"]:
            return None
        return j["data"]["cid"]  # first page’s cid


    async def get_playurl(self, bvid: str, quality: int = 0) -> Dict[str, Any]:
        """Get streaming URLs for a given BV video."""
        client = await self._get_client()
        cid = await self.get_cid(bvid)
        if cid is None:
            return {"success": False, "error": "Failed to find video content ID (cid)."}

        url = f"{self.base_url}/x/player/wbi/playurl"
        params = {
            "bvid": bvid,
            "cid": cid,
            "qn": quality,  # 0 means auto select
            "platform": "html5"
        }

        resp = await client.get(url, params=params)
        try:
            resp.raise_for_status()
            j = resp.json()
        except httpx.HTTPStatusError:
            return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text}"}
        except ValueError:
            return {"success": False, "error": "Invalid JSON from playurl endpoint."}

        if j.get("code") != 0:
            return {"success": False, "error": j.get("message", "Bilibili playurl error"), "code": j.get("code")}

        d = j.get("data", {})
        if "durl" not in d and "dash" not in d:
            return {"success": False, "error": "No playable URL in response."}

        return {"success": True, "data": d}
    
    
    async def get_video_info(self, bvid: str) -> Dict[str, Any]:
        client = await self._get_client()
        resp = await client.get(
            "https://api.bilibili.com/x/web-interface/view",
            params={"bvid": bvid}
        )
        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "error": data.get("message")}
        return {"success": True, "data": data["data"]}

    
    async def get_playinfo(self, bvid: str, cid: int, qn: int = 16) -> Dict[str, Any]:
        """
        Fetch signed play info (video URLs).
        """
        if not settings.SESSDATA or not settings.BILI_JCT:
            return {"success": False, "error": "Login required to fetch play URL."}
        client = await self._get_client()
        params = {
            "bvid": bvid, "cid": cid, "qn": qn, 
            "fnver": 0, "fnval": 1
        }
        resp = await client.get(
            "https://api.bilibili.com/x/player/wbi/playurl",
            params=params
        )
        data = resp.json()
        if data.get("code") != 0:
            return {"success": False, "error": data.get("message", "Failed to fetch playurl")}
        return {"success": True, "data": data["data"]}