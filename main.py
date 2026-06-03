import asyncio
import aiohttp
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

# 搜索 API 地址
SEARCH_API = "http://151.242.85.89:11191"


@register("astrbot_plugin_search", "lin", "联网搜索插件 - 支持文本搜索和图片搜索", "1.0.0", "https://github.com")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.api_base = SEARCH_API
    
    async def _request(self, endpoint: str, params: dict) -> dict:
        """发起HTTP请求"""
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self.api_base}{endpoint}", 
                params=params, 
                timeout=aiohttp.ClientTimeout(total=15)
            ) as resp:
                return await resp.json()
    
    @filter.command("搜")
    async def cmd_search(self, event: AstrMessageEvent):
        """文本搜索"""
        args = event.get_args()
        if not args:
            return CommandResult().error("用法：/搜 关键词\n例如：/搜 AI新闻")
        
        query = " ".join(args)
        
        try:
            data = await self._request("/search", {"q": query, "engine": "all", "num": 5})
            results = data.get("results", [])
            
            if not results:
                return CommandResult().error(f"没有找到「{query}」的结果喵～")
            
            msg = f"🔍 搜索「{query}」共 {data.get('number_of_results', 0)} 条结果：\n\n"
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "无标题")
                url = r.get("url", "")
                snippet = r.get("content", "")[:100]
                msg += f"【{i}】{title}\n"
                if snippet:
                    msg += f"    {snippet}\n"
                msg += f"    🔗 {url}\n\n"
            
            return CommandResult().message(Plain(msg))
            
        except Exception as e:
            return CommandResult().error(f"搜索出错了：{str(e)}")
    
    @filter.command("搜图")
    async def cmd_search_image(self, event: AstrMessageEvent):
        """图片搜索"""
        args = event.get_args()
        if not args:
            return CommandResult().error("用法：/搜图 关键词\n例如：/搜图 猫咪")
        
        query = " ".join(args)
        
        try:
            data = await self._request("/images", {"q": query, "num": 3})
            results = data.get("results", [])
            
            if not results:
                return CommandResult().error(f"没有找到「{query}」的图片喵～")
            
            messages = [Plain(f"🖼️ 搜索「{query}」找到 {len(results)} 张图片：\n")]
            for i, img in enumerate(results[:3], 1):
                url = img.get("url", "")
                if url:
                    messages.append(Plain(f"📷 图片 {i}:"))
                    messages.append(Image.fromURL(url))
            
            return CommandResult().message(*messages)
            
        except Exception as e:
            return CommandResult().error(f"图片搜索出错了：{str(e)}")
    
    @filter.command("搜索状态")
    async def cmd_search_status(self, event: AstrMessageEvent):
        """检查搜索服务状态"""
        try:
            data = await self._request("/health", {})
            cache_size = data.get("cache_size", 0)
            return CommandResult().message(Plain(f"✅ 搜索服务正常运行\n缓存大小: {cache_size}"))
        except Exception as e:
            return CommandResult().error(f"❌ 搜索服务不可用：{str(e)}")
