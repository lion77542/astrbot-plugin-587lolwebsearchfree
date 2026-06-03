import asyncio
import time
import socket
from collections import OrderedDict
import aiohttp
from astrbot.api.all import AstrMessageEvent, CommandResult, Context, Image, Plain
import astrbot.api.event.filter as filter
from astrbot.api.star import register, Star

# ========== 配置 ==========
SEARCH_API = "http://chat.587.lol:11190"
CACHE_SIZE = 30
CACHE_TTL = 300  # 5分钟
CONNECT_TIMEOUT = 3
READ_TIMEOUT = 8
MAX_TITLE_LEN = 50
MAX_CONTENT_LEN = 100
MAX_RESULTS = 5

# ========== DNS预解析 ==========
# 指定域名IP，避免每次DNS查询
DNS_CACHE = {"chat.587.lol": "151.242.85.89"}

def _patch_dns():
    """预解析DNS，加速连接"""
    orig_getaddrinfo = socket.getaddrinfo
    def patched_getaddrinfo(host, port, *args, **kwargs):
        if host in DNS_CACHE:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (DNS_CACHE[host], port))]
        return orig_getaddrinfo(host, port, *args, **kwargs)
    socket.getaddrinfo = patched_getaddrinfo

_patch_dns()


class LRUCache:
    """内存LRU缓存"""
    def __init__(self, maxsize=CACHE_SIZE, ttl=CACHE_TTL):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data = OrderedDict()
    
    def get(self, key):
        if key in self._data:
            val, ts = self._data[key]
            if time.time() - ts < self.ttl:
                self._data.move_to_end(key)
                return val
            del self._data[key]
        return None
    
    def set(self, key, val):
        if len(self._data) >= self.maxsize:
            self._data.popitem(last=False)
        self._data[key] = (val, time.time())
    
    def size(self):
        return len(self._data)


@register("astrbot_plugin_search", "lin", "联网搜索插件 - 支持文本搜索和图片搜索", "1.0.0", "https://github.com/lion77542/astrbot-plugin-587lolwebsearchfree")
class SearchPlugin(Star):
    def __init__(self, context: Context) -> None:
        super().__init__(context)
        self.api_base = SEARCH_API
        self._session = None
        self._cache = LRUCache()
        # 预热连接
        asyncio.create_task(self._warmup())
    
    async def _get_session(self):
        """复用连接池，保持长连接"""
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(
                limit=10,           # 最大连接数
                limit_per_host=5,   # 单主机最大连接
                ttl_dns_cache=300,  # DNS缓存5分钟
                keepalive_timeout=30, # 保活30秒
                force_close=False,   # 不强制关闭
            )
            self._session = aiohttp.ClientSession(
                connector=connector,
                timeout=aiohttp.ClientTimeout(
                    total=READ_TIMEOUT,
                    connect=CONNECT_TIMEOUT
                )
            )
        return self._session
    
    async def _warmup(self):
        """启动时预热连接"""
        try:
            session = await self._get_session()
            async with session.get(f"{self.api_base}/health") as resp:
                pass
        except:
            pass
    
    async def _request(self, endpoint: str, params: dict) -> dict:
        """发起HTTP请求（带缓存）"""
        cache_key = f"{endpoint}:{json.dumps(params, sort_keys=True)}"
        cached = self._cache.get(cache_key)
        if cached:
            return cached
        
        session = await self._get_session()
        async with session.get(f"{self.api_base}{endpoint}", params=params) as resp:
            data = await resp.json()
            self._cache.set(cache_key, data)
            return data
    
    @filter.command("搜")
    async def cmd_search(self, event: AstrMessageEvent):
        """文本搜索"""
        args = event.get_args()
        if not args:
            return CommandResult().error("用法：/搜 关键词\n例如：/搜 AI新闻")
        
        query = " ".join(args)
        
        try:
            data = await self._request("/search", {"q": query, "engine": "all", "num": MAX_RESULTS})
            results = data.get("results", [])
            
            if not results:
                return CommandResult().error(f"没有找到「{query}」的结果喵～")
            
            msg = f"🔍 搜索「{query}」共 {data.get('number_of_results', 0)} 条结果：\n\n"
            for i, r in enumerate(results[:MAX_RESULTS], 1):
                title = r.get("title", "无标题")
                url = r.get("url", "")
                snippet = r.get("content", "")[:MAX_CONTENT_LEN]
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
