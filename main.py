import asyncio
import aiohttp
import socket
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

SEARCH_API = "http://chat.587.lol:11191"
DNS_CACHE = {"chat.587.lol": "151.242.85.89"}

def _patch_dns():
    orig = socket.getaddrinfo
    def patched(host, port, *a, **k):
        if host in DNS_CACHE:
            return [(2, 1, 6, '', (DNS_CACHE[host], port))]
        return orig(host, port, *a, **k)
    socket.getaddrinfo = patched
_patch_dns()

@register("astrbot_plugin_search", "lin", "联网搜索插件", "0.0.1beta", "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def _fetch(self, url: str) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                return await resp.json()

    @filter.command("搜")
    async def cmd_search(self, message: AstrMessageEvent):
        query = message.message_str.replace("/搜", "").strip()
        if not query:
            return CommandResult().error("用法：/搜 关键词")

        try:
            url = f"{SEARCH_API}/search?q={query}&engine=all&num=5"
            data = await self._fetch(url)
            results = data.get("results", [])
            if not results:
                return CommandResult().error(f"没有找到「{query}」的结果")

            text = f"搜索「{query}」{len(results)}条结果：\n\n"
            for i, r in enumerate(results[:5], 1):
                title = str(r.get("title", ""))
                url2 = str(r.get("url", ""))
                text += f"{i}. {title}\n{url2}\n\n"

            return CommandResult().message(text)
        except Exception as e:
            return CommandResult().error(f"搜索出错：{str(e)}")

    @filter.command("搜图")
    async def cmd_search_image(self, message: AstrMessageEvent):
        query = message.message_str.replace("/搜图", "").strip()
        if not query:
            return CommandResult().error("用法：/搜图 关键词")

        try:
            url = f"{SEARCH_API}/images?q={query}&num=3"
            data = await self._fetch(url)
            results = data.get("results", [])
            if not results:
                return CommandResult().error(f"没有找到「{query}」的图片")

            text = f"搜索「{query}」图片：\n"
            for i, img in enumerate(results[:3], 1):
                url2 = str(img.get("url", ""))
                if url2:
                    text += f"{i}. {url2}\n"

            return CommandResult().message(text)
        except Exception as e:
            return CommandResult().error(f"图片搜索出错：{str(e)}")

    @filter.command("搜索状态")
    async def cmd_search_status(self, message: AstrMessageEvent):
        try:
            url = f"{SEARCH_API}/health"
            data = await self._fetch(url)
            return CommandResult().message("搜索服务正常")
        except Exception as e:
            return CommandResult().error(f"搜索服务不可用：{str(e)}")
