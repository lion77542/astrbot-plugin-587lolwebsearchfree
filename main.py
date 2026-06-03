import asyncio
import aiohttp
import socket
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

SEARCH_API = "http://sou.587.lol:11191"

@register("astrbot-plugin-587lolwebsearchfree", "lin", "联网搜索插件", "0.0.1beta", "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    @filter.command("搜")
    async def cmd_search(self, event: AstrMessageEvent):
        try:
            msg = str(event.message_str).replace("/搜", "").strip()
            if not msg:
                return CommandResult().message(Plain(text="用法：/搜 关键词"))

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{SEARCH_API}/search", params={"q": msg, "engine": "all", "num": 5}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
            
            results = data.get("results", [])
            if not results:
                return CommandResult().message(Plain(text=f"没有找到「{msg}」的结果"))

            text = f"搜索「{msg}」{len(results)}条结果：\n"
            for i, r in enumerate(results[:5], 1):
                title = str(r.get("title", ""))
                url = str(r.get("url", ""))
                text += f"{i}. {title}\n{url}\n"

            return CommandResult().message(Plain(text=str(text)))
        except Exception as e:
            return CommandResult().message(Plain(text=f"搜索出错：{str(e)}"))

    @filter.command("搜图")
    async def cmd_search_image(self, event: AstrMessageEvent):
        try:
            msg = str(event.message_str).replace("/搜图", "").strip()
            if not msg:
                return CommandResult().message(Plain(text="用法：/搜图 关键词"))

            async with aiohttp.ClientSession() as session:
                async with session.get(f"{SEARCH_API}/images", params={"q": msg, "num": 3}, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()

            results = data.get("results", [])
            if not results:
                return CommandResult().message(Plain(text=f"没有找到「{msg}」的图片"))

            msgs = [Plain(text=str(f"搜索「{msg}」图片："))]
            for img in results[:3]:
                url = str(img.get("url", ""))
                if url:
                    msgs.append(Image.fromURL(url))
            return CommandResult().message(*msgs)
        except Exception as e:
            return CommandResult().message(Plain(text=f"图片搜索出错：{str(e)}"))

    @filter.command("搜索状态")
    async def cmd_search_status(self, event: AstrMessageEvent):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(f"{SEARCH_API}/health", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    data = await resp.json()
            return CommandResult().message(Plain(text="搜索服务正常"))
        except Exception as e:
            return CommandResult().message(Plain(text=f"搜索服务不可用：{str(e)}"))
