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

@register("astrbot-plugin-587lolwebsearchfree", "lin", "联网搜索插件 - sou.587.lol 公益搜索", "0.0.1beta", "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)

    async def _fetch(self, url: str) -> dict:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                return await resp.json()

    @filter.llm_tool(name="web_search")
    async def web_search(self, event: AstrMessageEvent, query: str = "", num: int = 5) -> str:
        """联网搜索网页内容。当用户问你需要联网搜索的问题时使用此工具。

        Args:
            query: 搜索关键词
            num: 返回结果数量，默认5
        """
        if not query:
            return "请提供搜索关键词"
        
        try:
            url = f"{SEARCH_API}/search?q={query}&engine=all&num={num}"
            data = await self._fetch(url)
            results = data.get("results", [])
            
            if not results:
                return f"没有找到「{query}」的搜索结果"
            
            text = f"搜索「{query}」{len(results)}条结果：\n\n"
            for i, r in enumerate(results[:num], 1):
                title = str(r.get("title", ""))
                url2 = str(r.get("url", ""))
                snippet = str(r.get("content", ""))[:100]
                text += f"{i}. {title}\n"
                if snippet:
                    text += f"   {snippet}\n"
                text += f"   {url2}\n\n"
            
            return text
        except Exception as e:
            return f"搜索出错：{str(e)}"

    @filter.llm_tool(name="image_search")
    async def image_search(self, event: AstrMessageEvent, query: str = "", num: int = 3) -> str:
        """搜索网络图片。当用户需要找图片时使用此工具。

        Args:
            query: 搜索关键词
            num: 返回结果数量，默认3
        """
        if not query:
            return "请提供搜索关键词"
        
        try:
            url = f"{SEARCH_API}/images?q={query}&num={num}"
            data = await self._fetch(url)
            results = data.get("results", [])
            
            if not results:
                return f"没有找到「{query}」的图片"
            
            text = f"搜索「{query}」图片：\n"
            for i, img in enumerate(results[:num], 1):
                url2 = str(img.get("url", ""))
                if url2:
                    text += f"{i}. {url2}\n"
            
            return text
        except Exception as e:
            return f"图片搜索出错：{str(e)}"

    @filter.llm_tool(name="crawl_page")
    async def crawl_page(self, event: AstrMessageEvent, url: str = "", max_chars: int = 3000) -> str:
        """爬取网页内容，提取正文。当需要读取某个网页的内容时使用此工具。

        Args:
            url: 要爬取的网页地址
            max_chars: 最大返回字符数，默认3000
        """
        if not url:
            return "请提供网页地址"
        
        if not url.startswith("http"):
            url = "https://" + url

        try:
            api_url = f"{SEARCH_API}/crawl?url={url}&max_chars={max_chars}"
            data = await self._fetch(api_url)
            
            title = data.get("title", "无标题")
            content = data.get("content", "抓取失败")
            length = data.get("length", 0)
            
            text = f"📄 {title}\n\n{content}"
            if length > max_chars:
                text += f"\n\n...共{length}字"
            
            return text
        except Exception as e:
            return f"抓取失败：{str(e)}"

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
                text += f"{i}. {str(r.get('title', ''))}\n{str(r.get('url', ''))}\n\n"
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
                text += f"{i}. {str(img.get('url', ''))}\n"
            return CommandResult().message(text)
        except Exception as e:
            return CommandResult().error(f"图片搜索出错：{str(e)}")

    @filter.command("爬")
    async def cmd_crawl(self, message: AstrMessageEvent):
        url = message.message_str.replace("/爬", "").strip()
        if not url:
            return CommandResult().error("用法：/爬 网址")
        if not url.startswith("http"):
            url = "https://" + url
        try:
            api_url = f"{SEARCH_API}/crawl?url={url}&max_chars=3000"
            data = await self._fetch(api_url)
            title = data.get("title", "无标题")
            content = data.get("content", "抓取失败")
            length = data.get("length", 0)
            text = f"📄 {title}\n\n{content[:1500]}"
            if length > 1500:
                text += f"\n\n...共{length}字"
            return CommandResult().message(text)
        except Exception as e:
            return CommandResult().error(f"抓取失败：{str(e)}")
