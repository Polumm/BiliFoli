# core/bilibili_api.py
from __future__ import annotations

from typing import Any, Dict, Optional
import httpx
from .config import settings


class BilibiliAPI:
    """
    Thin async wrapper around a handful of Bilibili web endpoints.

    ‣ Accepts a *cookie jar* captured by OAuth login so that requests act as
      the logged-in user.
    ‣ `mid` can be supplied to query that user’s favourites instead of the
      fallback `settings.UP_MID`.
    """

    def __init__(
        self,
        cookies: Optional[dict[str, str]] = None,
        mid: Optional[int] = None,
    ) -> None:
        self.base_url = "https://api.bilibili.com"
        self._cookies = cookies or {}
        self._mid = mid
        self._client: Optional[httpx.AsyncClient] = None

    # ───────────────────────── context-manager ────────────────────────────────
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self._client:
            await self._client.aclose()

    # ───────────────────────── internal helpers ───────────────────────────────
    async def _client_async(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers=settings.HEADERS,
                cookies=self._cookies,
                timeout=settings.REQUEST_TIMEOUT,
                follow_redirects=True,
            )
        return self._client

    def _effective_mid(self) -> int | None:
        """Use `mid` from login if we have it, else fallback to env config."""
        return self._mid or getattr(settings, "UP_MID", None)

    # ───────────────────────── public API calls ───────────────────────────────
    async def get_favorite_folders(self) -> Dict[str, Any]:
        mid = self._effective_mid()
        if mid is None:
            return {"success": False, "error": "No UP_MID / user mid configured"}

        try:
            cli = await self._client_async()
            r = await cli.get(
                f"{self.base_url}/x/v3/fav/folder/created/list-all",
                params={"up_mid": mid},
            )
            r.raise_for_status()
            j = r.json()
            if j.get("code"):
                return {"success": False,
                        "error": f"API error {j['code']}: {j.get('message')}"}
            return {"success": True, "data": j["data"]["list"]}
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    async def get_folder_videos(
        self,
        media_id: int,
        page: int = 1,
        page_size: int = 20,
    ) -> Dict[str, Any]:
        page_size = max(1, min(page_size, settings.MAX_PAGE_SIZE))
        mid = self._effective_mid()
        if mid is None:
            return {"success": False, "error": "No UP_MID / user mid configured"}

        try:
            cli = await self._client_async()
            r = await cli.get(
                f"{self.base_url}/x/v3/fav/resource/list",
                params={
                    "up_mid": mid,
                    "media_id": media_id,
                    "pn": page,
                    "ps": page_size,
                    "platform": "web",
                },
            )
            r.raise_for_status()
            j = r.json()
            if j.get("code"):
                return {"success": False,
                        "error": f"API error {j['code']}: {j.get('message')}"}
            data = j["data"]
            videos = [
                {
                    "id": v.get("id"),
                    "title": v.get("title", "Untitled"),
                    "cover": v.get("cover",
                                   "https://i.ibb.co/C03gqfS/no-image.png"),
                    "bvid": v.get("bvid"),
                    "duration": v.get("duration", 0),
                    "pubtime": v.get("pubtime", 0),
                    "upper": v.get("upper", {}),
                    "cnt_info": v.get("cnt_info", {}),
                    "intro": v.get("intro", ""),
                }
                for v in data.get("medias", [])
            ]
            return {
                "success": True,
                "data": {
                    "info": data.get("info", {}),
                    "videos": videos,
                    "has_more": data.get("has_more", False),
                    "current_page": page,
                    "page_size": page_size,
                },
            }
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    # ───────────────────────── internal helpers ───────────────────────────────
    async def _get_cid(self, bvid: str) -> Optional[int]:
        cli = await self._client_async()
        r = await cli.get(f"{self.base_url}/x/web-interface/view",
                          params={"bvid": bvid})
        r.raise_for_status()
        j = r.json()
        return j.get("data", {}).get("cid") if j.get("code") == 0 else None

    # ───────────────────────── streaming helpers ──────────────────────────────
    async def get_playinfo(
        self,
        bvid: str,
        cid: int,
        *,
        qn: int = 16,
        fnval: int = 0,
    ) -> Dict[str, Any]:
        cli = await self._client_async()
        r = await cli.get(
            f"{self.base_url}/x/player/wbi/playurl",
            params={
                "bvid": bvid,
                "cid": cid,
                "qn": qn,
                "fnver": 0,
                "fnval": fnval,
                "platform": "html5",
            },
        )
        j = r.json()
        if j.get("code"):
            return {
                "success": False,
                "error": j.get("message", "playurl error"),
                "code": j.get("code"),
            }
        return {"success": True, "data": j.get("data", {})}

    async def get_muxed_mp4(
        self,
        bvid: str,
        *,
        qualities: tuple[int, ...] = (16, 32, 48),
    ) -> Optional[str]:
        cid = await self._get_cid(bvid)
        if cid is None:
            return None
        for q in qualities:
            res = await self.get_playinfo(bvid, cid, qn=q)
            if not res["success"]:
                continue
            durl = res["data"].get("durl") or []
            if durl:
                mp4s = [seg["url"] for seg in durl
                        if ".mp4" in seg["url"].lower()]
                return mp4s[0] if mp4s else durl[0]["url"]
        return None
