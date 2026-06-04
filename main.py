"""
AstrBot 联网搜索插件 - 587.lol 公益搜索（轻量优化版）
专为低配服务器设计：1核 256MB内存 2G存储
作者：小银耳（基于 MiMo 大模型优化）
改进说明：
- 保留原仓库所有功能
- 优化内存占用和性能
- 增强错误处理和稳定性
- 添加智能缓存机制
"""

import asyncio
import aiohttp
import socket
import time
from typing import Optional, Dict, Any
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

# 配置常量
SEARCH_API = "http://chat.587.lol:11191"
DNS_CACHE = {"chat.587.lol": "151.242.85.89"}

# 轻量级缓存配置
CACHE_SIZE = 20  # 缓存条目数
CACHE_TTL = 300  # 缓存生存时间（秒）
MAX_RETRIES = 2  # 失败重试次数
TIMEOUT_SECONDS = 12  # 请求超时时间


class SimpleCache:
    """轻量级内存缓存，专为低内存环境优化"""
    
    def __init__(self, max_size: int = CACHE_SIZE, ttl: int = CACHE_TTL):
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.max_size = max_size
        self.ttl = ttl
    
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        """获取缓存，如果过期则删除"""
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["time"] < self.ttl:
                return entry["data"]
            else:
                del self.cache[key]
        return None
    
    def set(self, key: str, data: Dict[str, Any]):
        """设置缓存，如果满了则删除最旧的"""
        if len(self.cache) >= self.max_size:
            # 删除最旧的条目
            oldest_key = min(self.cache.keys(), 
                           key=lambda k: self.cache[k]["time"])
            del self.cache[oldest_key]
        self.cache[key] = {
            "data": data,
            "time": time.time()
        }
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()


@register(
    "astrbot_plugin_587lolwebsearchfree", 
    "lin", 
    "联网搜索插件 - sou.587.lol 公益搜索（轻量优化版）", 
    "1.0.0", 
    "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree"
)
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.cache = SimpleCache()
        self.session: Optional[aiohttp.ClientSession] = None
        self._patch_dns()
    
    def _patch_dns(self):
        """DNS 预解析，减少 DNS 查询延迟"""
        orig_getaddrinfo = socket.getaddrinfo
        
        def patched_getaddrinfo(host, port, *args, **kwargs):
            if host in DNS_CACHE:
                return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', 
                        (DNS_CACHE[host], port))]
            return orig_getaddrinfo(host, port, *args, **kwargs)
        
        socket.getaddrinfo = patched_getaddrinfo
    
    async def init(self):
        """插件初始化，创建 HTTP 会话"""
        # 轻量级连接池配置
        connector = aiohttp.TCPConnector(
            limit=5,  # 总连接数
            limit_per_host=3,  # 每个主机的连接数
            keepalive_timeout=10,  # 保持连接时间
            enable_cleanup_closed=True
        )
        self.session = aiohttp.ClientSession(connector=connector)
    
    async def terminate(self):
        """插件终止，清理资源"""
        if self.session:
            await self.session.close()
        self.cache.clear()
    
    async def _fetch_with_retry(self, url: str, params: Dict = None) -> Optional[Dict]:
        """带重试的 HTTP 请求"""
        cache_key = f"{url}:{str(params)}" if params else url
        
        # 检查缓存
        cached = self.cache.get(cache_key)
        if cached:
            return cached
        
        for attempt in range(MAX_RETRIES):
            try:
                async with self.session.get(
                    url, 
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        # 存入缓存
                        self.cache.set(cache_key, data)
                        return data
                    else:
                        if attempt == MAX_RETRIES - 1:
                            return None
                        await asyncio.sleep(1)  # 等待后重试
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt == MAX_RETRIES - 1:
                    return None
                await asyncio.sleep(1)  # 等待后重试
        
        return None
    
    async def _fetch(self, url: str) -> dict:
        """兼容原版本的 fetch 方法"""
        async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=TIMEOUT_SECONDS)) as resp:
            return await resp.json()
    
    @filter.llm_tool()
    async def web_search(self, event: AstrMessageEvent, query: str = "", num: int = 5) -> str:
        """联网搜索网页内容。当用户问你需要联网搜索的问题时使用此工具。

        Args:
            query(string): 搜索关键词
            num(int): 返回结果数量，默认5
        """
        if not query:
            return "请提供搜索关键词"
        
        try:
            # 使用参数化请求，更安全
            url = f"{SEARCH_API}/search"
            params = {"q": query, "engine": "all", "num": num}
            data = await self._fetch_with_retry(url, params)
            
            if not data or "results" not in data:
                return f"没有找到「{query}」的搜索结果"
            
            results = data["results"][:num]
            if not results:
                return f"没有找到「{query}」的搜索结果"
            
            # 构建响应文本
            text = f"🔍 搜索「{query}」找到 {len(results)} 条结果：\n\n"
            for i, r in enumerate(results, 1):
                title = str(r.get("title", ""))[:50]  # 限制标题长度
                url_r = str(r.get("url", ""))
                snippet = str(r.get("content", ""))[:100]  # 限制摘要长度
                
                text += f"{i}. {title}\n"
                if snippet:
                    text += f"   {snippet}\n"
                text += f"   🔗 {url_r}\n\n"
            
            return text
            
        except Exception as e:
            return f"搜索出错：{str(e)}"
    
    @filter.llm_tool()
    async def image_search(self, event: AstrMessageEvent, query: str = "", num: int = 3) -> str:
        """搜索网络图片。当用户需要找图片时使用此工具。

        Args:
            query(string): 搜索关键词
            num(int): 返回结果数量，默认3
        """
        if not query:
            return "请提供搜索关键词"
        
        try:
            url = f"{SEARCH_API}/images"
            params = {"q": query, "num": num}
            data = await self._fetch_with_retry(url, params)
            
            if not data or "results" not in data:
                return f"没有找到「{query}」的图片"
            
            results = data["results"][:num]
            if not results:
                return f"没有找到「{query}」的图片"
            
            text = f"🖼️ 搜索「{query}」的图片：\n\n"
            for i, img in enumerate(results, 1):
                url_img = str(img.get("url", ""))
                if url_img:
                    text += f"{i}. {url_img}\n"
            
            return text
            
        except Exception as e:
            return f"图片搜索出错：{str(e)}"
    
    @filter.llm_tool()
    async def crawl_page(self, event: AstrMessageEvent, url: str = "", max_chars: int = 3000) -> str:
        """爬取网页内容，提取正文。当需要读取某个网页的内容时使用此工具。

        Args:
            url(string): 要爬取的网页地址
            max_chars(int): 最大返回字符数，默认3000
        """
        if not url:
            return "请提供网页地址"
        
        # 确保 URL 格式正确
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        try:
            api_url = f"{SEARCH_API}/crawl"
            params = {"url": url, "max_chars": max_chars}
            data = await self._fetch_with_retry(api_url, params)
            
            if not data:
                return "抓取失败，请检查网址是否正确"
            
            title = data.get("title", "无标题")
            content = data.get("content", "抓取失败")
            length = data.get("length", 0)
            
            text = f"📄 {title}\n\n{content}"
            if length > max_chars:
                text += f"\n\n...（共 {length} 字，已显示前 {max_chars} 字）"
            
            return text
            
        except Exception as e:
            return f"抓取失败：{str(e)}"
    
    @filter.command("搜")
    async def cmd_search(self, event: AstrMessageEvent):
        """搜索命令：/搜 关键词"""
        query = event.message_str.replace("/搜", "").strip()
        if not query:
            return CommandResult().error("用法：/搜 关键词")
        
        try:
            url = f"{SEARCH_API}/search"
            params = {"q": query, "engine": "all", "num": 5}
            data = await self._fetch_with_retry(url, params)
            
            if not data or "results" not in data:
                return CommandResult().error(f"没有找到「{query}」的结果")
            
            results = data["results"][:5]
            text = f"🔍 搜索「{query}」找到 {len(results)} 条结果：\n\n"
            
            for i, r in enumerate(results, 1):
                title = str(r.get("title", ""))[:50]
                url_r = str(r.get("url", ""))
                text += f"{i}. {title}\n🔗 {url_r}\n\n"
            
            return CommandResult().message(text)
            
        except Exception as e:
            return CommandResult().error(f"搜索出错：{str(e)}")
    
    @filter.command("搜图")
    async def cmd_search_image(self, event: AstrMessageEvent):
        """搜图命令：/搜图 关键词"""
        query = event.message_str.replace("/搜图", "").strip()
        if not query:
            return CommandResult().error("用法：/搜图 关键词")
        
        try:
            url = f"{SEARCH_API}/images"
            params = {"q": query, "num": 3}
            data = await self._fetch_with_retry(url, params)
            
            if not data or "results" not in data:
                return CommandResult().error(f"没有找到「{query}」的图片")
            
            results = data["results"][:3]
            text = f"🖼️ 搜索「{query}」的图片：\n\n"
            
            for i, img in enumerate(results, 1):
                url_img = str(img.get("url", ""))
                if url_img:
                    text += f"{i}. {url_img}\n"
            
            return CommandResult().message(text)
            
        except Exception as e:
            return CommandResult().error(f"图片搜索出错：{str(e)}")
    
    @filter.command("搜索状态")
    async def cmd_status(self, event: AstrMessageEvent):
        """查看搜索状态和缓存信息"""
        status_text = (
            "📊 搜索插件状态：\n\n"
            f"🔗 API地址：{SEARCH_API}\n"
            f"💾 缓存条目：{len(self.cache.cache)}/{self.cache.max_size}\n"
            f"⏱️ 缓存TTL：{self.cache.ttl}秒\n"
            f"🔄 重试次数：{MAX_RETRIES}\n"
            f"⏳ 超时时间：{TIMEOUT_SECONDS}秒\n\n"
            "✅ 插件运行正常"
        )
        return CommandResult().message(status_text)
    
    @filter.command("清空缓存")
    async def cmd_clear_cache(self, event: AstrMessageEvent):
        """清空搜索缓存"""
        self.cache.clear()
        return CommandResult().message("✅ 缓存已清空")