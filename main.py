import asyncio
import time
import socket
import json as _json
from collections import OrderedDict
import aiohttp
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

SEARCH_API = "http://sou.587.lol:11191"
DNS_CACHE = {"sou.587.lol": "151.242.85.89"}

def _patch_dns():
    orig = socket.getaddrinfo
    def patched(host, port, *a, **k):
        if host in DNS_CACHE:
            return [(2, 1, 6, '', (DNS_CACHE[host], port))]
        return orig(host, port, *a, **k)
    socket.getaddrinfo = patched
_patch_dns()


@register("astrbot_plugin_sou587", "lin", "联网搜索插件", "1.0.0", "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self._session = None

    async def _get_session(self):
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(limit=10, limit_per_host=5),
                timeout=aiohttp.ClientTimeout(total=10, connect=3)
            )
        return self._session

    async def _fetch(self, url: str) -> dict:
        session = await self._get_session()
        async with session.get(url) as resp:
            return await resp.json()

    @filter.command("搜")
    async def cmd_search(self, event: AstrMessageEvent):
        query = event.message_str.replace("/搜", "").strip()
        if not query:
            return CommandResult().message(Plain("用法：/搜 关键词"))

        try:
            url = f"{SEARCH_API}/search?q={query}&engine=all&num=5"
            data = await self._fetch(url)
            results = data.get("results", [])
            if not results:
                return CommandResult().message(Plain(f"没有找到「{query}」的结果"))

            text = f"搜索「{query}」{len(results)}条结果：\n\n"
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "")
                url2 = r.get("url", "")
                text += f"{i}. {title}\n{url2}\n\n"

            return CommandResult().message(Plain(text))
        except Exception as e:
            return CommandResult().message(Plain(f"搜索出错：{str(e)}"))

    @filter.command("搜图")
    async def cmd_search_image(self, event: AstrMessageEvent):
        query = event.message_str.replace("/搜图", "").strip()
        if not query:
            return CommandResult().message(Plain("用法：/搜图 关键词"))

        try:
            url = f"{SEARCH_API}/images?q={query}&num=3"
            data = await self._fetch(url)
            results = data.get("results", [])
            if not results:
                return CommandResult().message(Plain(f"没有找到「{query}」的图片"))

            msgs = [Plain(f"搜索「{query}」图片：")]
            for img in results[:3]:
                msgs.append(Image.fromURL(img.get("url", "")))
            return CommandResult().message(*msgs)
        except Exception as e:
            return CommandResult().message(Plain(f"图片搜索出错：{str(e)}"))

    @filter.command("搜索状态")
    async def cmd_search_status(self, event: AstrMessageEvent):
        try:
            url = f"{SEARCH_API}/health"
            data = await self._fetch(url)
            return CommandResult().message(Plain(f"搜索服务正常"))
        except Exception as e:
            return CommandResult().message(Plain(f"搜索服务不可用：{str(e)}"))
