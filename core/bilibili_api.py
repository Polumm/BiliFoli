import json
from typing import Dict, Any, Optional

import httpx

from .config import settings


class BilibiliAPI:
    """Simple (unauthenticated) wrapper around a handful of Bilibili endpoints."""

    def __init__(self) -> None:
        self.base_url = "https://api.bilibili.com"
        self.client: Optional[httpx.AsyncClient] = None

    # ────────────────────────────────────────────────────────────────────── utils ────
    async def _get_client(self) -> httpx.AsyncClient:
        if self.client is None:
            self.client = httpx.AsyncClient(
                headers=settings.HEADERS,
                timeout=settings.REQUEST_TIMEOUT,
                follow_redirects=True,  # some regional CDNs still 302 → *.mcdn.bilivideo.cn
            )
        return self.client

    async def close(self) -> None:
        if self.client is not None:
            await self.client.aclose()
            self.client = None

    # ───────────────────────────────────────────────────────────── configuration ────
    def check_config(self) -> Optional[str]:
        if not settings.is_configured():
            return "Missing required environment variables: " + ", ".join(settings.get_missing_config())
        return None

    # ─────────────────────────────────────────────────────── favourites / folders ────
    async def get_favorite_folders(self) -> Dict[str, Any]:
        """Return the user’s own favourite‑folder list."""
        try:
            cli = await self._get_client()
            r = await cli.get(
                f"{self.base_url}/x/v3/fav/folder/created/list-all",
                params={"up_mid": settings.UP_MID},
            )
            r.raise_for_status()
            j = r.json()
            if j.get("code"):
                return {"success": False, "error": f"Bilibili API error {j.get('code')}: {j.get('message')}"}
            return {"success": True, "data": j["data"]["list"]}
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return {"success": False, "error": f"Network/HTTP error: {e}"}
        except (json.JSONDecodeError, KeyError) as e:
            return {"success": False, "error": f"Bad JSON from Bilibili: {e}"}

    async def get_folder_videos(self, media_id: int, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        page_size = max(1, min(page_size, settings.MAX_PAGE_SIZE))
        try:
            cli = await self._get_client()
            r = await cli.get(
                f"{self.base_url}/x/v3/fav/resource/list",
                params={
                    "up_mid": settings.UP_MID,
                    "media_id": media_id,
                    "pn": page,
                    "ps": page_size,
                    "platform": "web",
                },
            )
            r.raise_for_status()
            j = r.json()
            if j.get("code"):
                return {"success": False, "error": f"Bilibili API error {j.get('code')}: {j.get('message')}"}

            data = j["data"]
            videos = [
                {
                    "id": v.get("id"),
                    "title": v.get("title", "Untitled"),
                    "cover": v.get("cover", "https://i.ibb.co/C03gqfS/no-image.png"),
                    "bvid": v.get("bvid"),
                    "duration": v.get("duration", 0),
                    "pubtime": v.get("pubtime", 0),
                    "upper": v.get("upper", {}),
                    "cnt_info": v.get("cnt_info", {}),
                    "intro": v.get("intro", ""),
                }
                for v in data.get("medias", [])
                if v
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
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return {"success": False, "error": f"Network/HTTP error: {e}"}
        except (json.JSONDecodeError, KeyError) as e:
            return {"success": False, "error": f"Bad JSON from Bilibili: {e}"}

    # ───────────────────────────────────────────────────────────── playback helpers ────
    async def _get_cid(self, bvid: str) -> Optional[int]:
        cli = await self._get_client()
        r = await cli.get(f"{self.base_url}/x/web-interface/view", params={"bvid": bvid})
        r.raise_for_status()
        j = r.json()
        return j.get("data", {}).get("cid") if j.get("code") == 0 else None

    async def get_playinfo(self, bvid: str, cid: int, *, qn: int = 16, fnval: int = 0) -> Dict[str, Any]:
        cli = await self._get_client()
        r = await cli.get(
            f"{self.base_url}/x/player/wbi/playurl",
            params={"bvid": bvid, "cid": cid, "qn": qn, "fnver": 0, "fnval": fnval, "platform": "html5"},
        )
        j = r.json()
        if j.get("code"):
            return {"success": False, "error": j.get("message", "playurl error"), "code": j.get("code")}
        return {"success": True, "data": j.get("data", {})}

    async def get_muxed_mp4(self, bvid: str, *, qualities=(16, 32, 48)) -> Optional[str]:
        cid = await self._get_cid(bvid)
        if cid is None:
            return None
        for q in qualities:
            res = await self.get_playinfo(bvid, cid, qn=q)
            if not res["success"]:
                continue
            durl = res["data"].get("durl") or []
            if durl:
                mp4s = [seg["url"] for seg in durl if ".mp4" in seg["url"].lower()]
                return mp4s[0] if mp4s else durl[0]["url"]
        return None

    async def get_view(self, bvid: str) -> Dict[str, Any]:
        try:
            cli = await self._get_client()
            r = await cli.get(f"{self.base_url}/x/web-interface/view", params={"bvid": bvid})
            r.raise_for_status()
            j = r.json()
            if j.get("code"):
                return {"success": False, "error": f"Bilibili API error {j.get('code')}: {j.get('message')}"}
            return {"success": True, "data": j.get("data", {})}
        except (httpx.RequestError, httpx.HTTPStatusError) as e:
            return {"success": False, "error": f"Network/HTTP error: {e}"}
        except (json.JSONDecodeError, KeyError) as e:
            return {"success": False, "error": f"Bad JSON from Bilibili: {e}"}

    async def get_playlist(self, bvid: str) -> Dict[str, Any]:
        view = await self.get_view(bvid)
        if not view["success"]:
            return view

        data = view["data"] or {}

        # Prefer ugc_season (合集/系列) when it contains multiple episodes
        ugc = data.get("ugc_season") or {}
        sections = ugc.get("sections") or []
        if sections:
            items = []
            for section in sections:
                for ep in (section.get("episodes") or []):
                    arc = ep.get("arc") or {}
                    ep_bvid = ep.get("bvid") or (arc.get("bvid") if isinstance(arc, dict) else None)
                    ep_cid = ep.get("cid") or ((ep.get("page") or {}).get("cid") if isinstance(ep.get("page"), dict) else None)
                    if not ep_bvid or not ep_cid:
                        continue

                    title = ep.get("title") or (arc.get("title") if isinstance(arc, dict) else None) or f"Episode {len(items)+1}"
                    duration = 0
                    if isinstance(ep.get("page"), dict):
                        duration = ep["page"].get("duration") or 0
                    if not duration and isinstance(arc, dict):
                        duration = arc.get("duration") or 0

                    items.append({"bvid": ep_bvid, "cid": ep_cid, "title": title, "duration": duration})

            if len(items) > 1:
                return {
                    "success": True,
                    "data": {
                        "type": "ugc_season",
                        "title": ugc.get("title") or data.get("title") or "",
                        "items": items,
                    },
                }

        # Otherwise: multi-P pages inside this bvid
        pages = data.get("pages") or []
        if isinstance(pages, list) and len(pages) > 1:
            items = []
            for p in pages:
                if not p or not p.get("cid"):
                    continue
                items.append({
                    "bvid": bvid,
                    "cid": p.get("cid"),
                    "page": p.get("page"),
                    "title": p.get("part") or f"P{p.get('page')}",
                    "duration": p.get("duration") or 0,
                })
            return {
                "success": True,
                "data": {"type": "pages", "title": data.get("title") or "", "items": items},
            }

        # Single fallback
        cid = data.get("cid")
        if cid:
            return {
                "success": True,
                "data": {
                    "type": "single",
                    "title": data.get("title") or "",
                    "items": [{"bvid": bvid, "cid": cid, "page": 1, "title": data.get("title") or "Untitled", "duration": data.get("duration") or 0}],
                },
            }

        return {"success": False, "error": "No playlist info found"}

    async def get_muxed_mp4(
        self,
        bvid: str,
        cid: Optional[int] = None,
        *,
        qualities=(16, 32, 48)
    ) -> Optional[str]:
        if cid is None:
            cid = await self._get_cid(bvid)
        if cid is None:
            return None

        for q in qualities:
            res = await self.get_playinfo(bvid, cid, qn=q)
            if not res["success"]:
                continue
            durl = res["data"].get("durl") or []
            if durl:
                mp4s = [seg["url"] for seg in durl if ".mp4" in seg["url"].lower()]
                return mp4s[0] if mp4s else durl[0]["url"]
        return None