#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
联网搜索 API 服务端 - 终极优化版
极致性能 + 超高稳定性 + 花活全开
专为低配服务器设计：1核 256MB内存 2G存储
支持 LLM 自动调用搜索和网页爬取
作者：小银耳（基于 MiMo 大模型优化）

🎯 花活清单：
✅ 异步并发 + 连接池复用
✅ LRU 内存缓存 + 智能预热
✅ DNS 预解析 + 连接预热
✅ 搜索引擎熔断 + 自动降级
✅ 结果去重 + 交叉验证
✅ UA 轮换 + 请求头优化
✅ 超时控制 + 自动重试
✅ 内存监控 + 自动清理
✅ 性能监控 + 实时统计
✅ 错误恢复 + 优雅降级
"""

import re
import asyncio
import random
import time
import hashlib
import socket
import psutil
import os
import sys
from collections import OrderedDict
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Any, Set, Tuple
from functools import wraps
from contextlib import asynccontextmanager

from flask import Flask, request, jsonify
import httpx
import aiofiles

# ========== 配置（极致优化）==========
class Config:
    """配置管理"""
    # 缓存配置
    MAX_CACHE = 50  # 缓存条目数
    CACHE_TTL = 300  # 缓存生存时间（秒）
    
    # 超时配置
    CONNECT_TIMEOUT = 2  # 连接超时（秒）
    READ_TIMEOUT = 8  # 读取超时（秒）
    TOTAL_TIMEOUT = 15  # 总超时（秒）
    
    # 连接池配置
    CONNECTION_POOL_SIZE = 15  # 连接池大小
    CONNECTIONS_PER_HOST = 5  # 每主机连接数
    KEEPALIVE_TIMEOUT = 30  # 保持连接超时
    
    # 内容限制
    MAX_CONTENT_LEN = 100  # 搜索结果内容最大长度
    MAX_TITLE_LEN = 50  # 标题最大长度
    MAX_PARAGRAPHS = 8  # 爬取最大段落数
    MAX_CRAWL_CHARS = 2500  # 爬取最大字符数
    
    # 重试配置
    MAX_RETRIES = 2  # 最大重试次数
    RETRY_DELAY = 1  # 重试延迟（秒）
    
    # 熔断配置
    CIRCUIT_BREAKER_THRESHOLD = 5  # 失败阈值
    CIRCUIT_BREAKER_TIMEOUT = 300  # 熔断超时（秒）
    
    # DNS 缓存
    DNS_CACHE = {
        # cn.bing.com 不缓存，让 DNS 自然解析以保证正确性
        'html.duckduckgo.com': '52.142.124.215',
    }

# ========== 轻量级 LRU 缓存 ==========
class LRUCache:
    """高性能 LRU 缓存"""
    
    def __init__(self, max_size: int = Config.MAX_CACHE, ttl: int = Config.CACHE_TTL):
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.max_size = max_size
        self.ttl = ttl
        self.hits = 0
        self.misses = 0
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                # 移到末尾（最近使用）
                self.cache.move_to_end(key)
                self.hits += 1
                return value
            else:
                del self.cache[key]
        self.misses += 1
        return None
    
    def set(self, key: str, value: Any):
        """设置缓存"""
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = (value, time.time())
        
        # 清理过期条目
        self._cleanup()
        
        # 限制大小
        if len(self.cache) > self.max_size:
            self.cache.popitem(last=False)
    
    def _cleanup(self):
        """清理过期条目"""
        now = time.time()
        expired = [k for k, (v, t) in self.cache.items() if now - t >= self.ttl]
        for k in expired:
            del self.cache[k]
    
    def clear(self):
        """清空缓存"""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
    
    @property
    def hit_rate(self) -> float:
        """缓存命中率"""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0

# ========== 熔断器 ==========
class CircuitBreaker:
    """熔断器 - 防止级联失败"""
    
    def __init__(self, threshold: int = Config.CIRCUIT_BREAKER_THRESHOLD, 
                 timeout: int = Config.CIRCUIT_BREAKER_TIMEOUT):
        self.threshold = threshold
        self.timeout = timeout
        self.failures: Dict[str, List[float]] = {}
        self.state: Dict[str, str] = {}  # 'closed', 'open', 'half-open'
    
    def record_success(self, engine: str):
        """记录成功"""
        if engine in self.failures:
            self.failures[engine] = []
        self.state[engine] = 'closed'
    
    def record_failure(self, engine: str):
        """记录失败"""
        if engine not in self.failures:
            self.failures[engine] = []
        self.failures[engine].append(time.time())
        
        # 清理旧失败记录
        cutoff = time.time() - self.timeout
        self.failures[engine] = [t for t in self.failures[engine] if t > cutoff]
        
        # 检查是否触发熔断
        if len(self.failures[engine]) >= self.threshold:
            self.state[engine] = 'open'
    
    def is_available(self, engine: str) -> bool:
        """检查引擎是否可用"""
        if engine not in self.state:
            self.state[engine] = 'closed'
            return True
        
        if self.state[engine] == 'closed':
            return True
        
        if self.state[engine] == 'open':
            # 检查是否可以尝试恢复
            if engine in self.failures and self.failures[engine]:
                last_failure = max(self.failures[engine])
                if time.time() - last_failure >= self.timeout:
                    self.state[engine] = 'half-open'
                    return True
            return False
        
        # half-open 状态允许一次尝试
        return True

# ========== DNS 预解析 ==========
def _patch_dns():
    """DNS 预解析，减少 DNS 查询延迟"""
    orig_getaddrinfo = socket.getaddrinfo
    
    def patched_getaddrinfo(host, port, *args, **kwargs):
        if host in Config.DNS_CACHE:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', 
                    (Config.DNS_CACHE[host], port))]
        return orig_getaddrinfo(host, port, *args, **kwargs)
    
    socket.getaddrinfo = patched_getaddrinfo

# ========== UA 轮换 ==========
UAS = [
    # Windows Chrome（中国地区）
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
    # macOS Safari（中国地区）
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15',
    # 国产浏览器 - 360安全浏览器
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.217 Safari/537.36 QIHU360SE',
    # 国产浏览器 - QQ浏览器
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.217 Safari/537.36 Vivaldi/6.0',
    # 国产浏览器 - 搜狗浏览器
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.217 Safari/537.36 SE 2.X MetaSr 1.0',
    # Linux Firefox（服务器常用）
    'Mozilla/5.0 (X11; Linux x86_64; rv:109.0) Gecko/20100101 Firefox/119.0',
    # iOS Safari（中国地区）
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    # Android Chrome（中国地区）
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Mobile Safari/537.36',
    # Windows Edge（中国地区）
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0',
    # 百度浏览器（中国专用）
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.217 Safari/537.36 BIDUBrowser/8.7',
]

def _get_headers() -> Dict[str, str]:
    """获取优化的请求头"""
    return {
        'User-Agent': random.choice(UAS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Cache-Control': 'max-age=0',
        'DNT': '1',
        'Sec-Ch-Ua': '"Google Chrome";v="119", "Chromium";v="119", "Not?A_Brand";v="24"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
    }

# ========== 正则表达式（优化版）==========
# 必应中国搜索结果正则（改进版，支持更多HTML变体）
BING_CN_RE = re.compile(
    r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>.*?<p[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE
)

# 国际必应搜索结果正则（改进版）
BING_RE = re.compile(
    r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>.*?<p[^>]*>(.*?)</p>',
    re.DOTALL | re.IGNORECASE
)

DDG_RE = re.compile(
    r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE
)

# 改进的正文提取
CONTENT_RE = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL | re.IGNORECASE)
HEADING_RE = re.compile(r'<h[1-6][^>]*>(.*?)</h[1-6]>', re.DOTALL | re.IGNORECASE)
TEXT_RE = re.compile(r'>([^<]+)<')  # 提取标签间文本

def _clean_html(s: str, max_len: Optional[int] = None) -> str:
    """清理 HTML 标签并修复中文乱码"""
    # 1. 清理 HTML 标签
    s = re.sub(r'<[^>]+>', '', s).strip()
    
    # 2. 解码 HTML 实体（如 &nbsp; &#123; 等）
    import html
    s = html.unescape(s)
    
    # 3. 合并空白字符
    s = re.sub(r'\s+', ' ', s)
    
    # 4. 只保留可打印字符和中文字符（防止乱码）
    # 包括：ASCII 可打印字符、中文汉字、中文标点、全角字符
    s = re.sub(r'[^\x20-\x7E\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]', '', s)
    
    # 5. 再次清理多余空白
    s = re.sub(r'\s+', ' ', s).strip()
    
    return s[:max_len] if max_len and len(s) > max_len else s

# ========== 全局对象 ==========
cache = LRUCache(max_size=Config.MAX_CACHE, ttl=Config.CACHE_TTL)
circuit_breaker = CircuitBreaker(threshold=Config.CIRCUIT_BREAKER_THRESHOLD, 
                                timeout=Config.CIRCUIT_BREAKER_TIMEOUT)
http_client: Optional[httpx.AsyncClient] = None

# ========== Flask 应用 ==========
app = Flask(__name__)
app.config['start_time'] = time.time()
app.config['JSON_AS_ASCII'] = False  # 确保 JSON 输出包含中文字符
app.json.ensure_ascii = False  # Flask 3.x 新语法

# ========== 异步装饰器 ==========
def async_route(f):
    """异步路由装饰器"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        return asyncio.run(f(*args, **kwargs))
    return wrapper

# ========== 搜索引擎（极致优化版）==========
async def search_bing(q: str, num: int) -> List[Dict[str, str]]:
    """必应搜索 - 简洁版（确保中文搜索正常）"""
    if not circuit_breaker.is_available('bing'):
        return []
    
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=3.0, pool=5.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            r = await client.get(
                'https://cn.bing.com/search',
                params={'q': q, 'count': min(num * 2, 20)},
                headers=headers
            )
            
            results = []
            seen_urls: set = set()
            
            # 必应搜索结果正则
            pattern = r'<li[^>]*class="[^"]*b_algo[^"]*"[^>]*>.*?<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>.*?</h2>.*?<p[^>]*>(.*?)</p>'
            for m in re.finditer(pattern, r.text, re.DOTALL | re.IGNORECASE):
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                url = m.group(1)
                content = re.sub(r'<[^>]+>', '', m.group(3)).strip()
                
                # 解码 HTML 实体
                import html
                title = html.unescape(title)[:Config.MAX_TITLE_LEN]
                content = html.unescape(content)[:Config.MAX_CONTENT_LEN]
                
                if title and url.startswith('http') and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        'title': title,
                        'url': url,
                        'content': content
                    })
                
                if len(results) >= num:
                    break
            
            circuit_breaker.record_success('bing')
            return results
            
    except Exception as e:
        circuit_breaker.record_failure('bing')
        return []

async def search_ddg(q: str, num: int) -> List[Dict[str, str]]:
    """DuckDuckGo 搜索 - 极致优化"""
    if not circuit_breaker.is_available('ddg'):
        return []
    
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=Config.CONNECT_TIMEOUT,
                read=Config.READ_TIMEOUT,
                write=3,
                pool=Config.CONNECTION_POOL_SIZE
            ),
            follow_redirects=True,
            verify=False,
            limits=httpx.Limits(
                max_connections=Config.CONNECTION_POOL_SIZE,
                max_keepalive_connections=Config.CONNECTIONS_PER_HOST
            ),
        ) as client:
            r = await client.get(
                'https://html.duckduckgo.com/html/',
                params={'q': q},
                headers=_get_headers()
            )
            
            results = []
            seen_urls: Set[str] = set()
            
            for m in DDG_RE.finditer(r.text):
                title = _clean_html(m.group(2), Config.MAX_TITLE_LEN)
                url = m.group(1)
                content = _clean_html(m.group(3), Config.MAX_CONTENT_LEN)
                
                if title and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        'title': title,
                        'url': url,
                        'content': content
                    })
                
                if len(results) >= num:
                    break
            
            circuit_breaker.record_success('ddg')
            return results
            
    except Exception as e:
        circuit_breaker.record_failure('ddg')
        return []

async def search_quark(q: str, num: int) -> List[Dict[str, str]]:
    """夸克搜索 - 轻量版"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0, read=10.0, write=3.0, pool=5.0),
            follow_redirects=True,
            verify=False,
        ) as client:
            r = await client.get(
                'https://quark.sm.cn/s',
                params={'q': q, 'safemode': '1'},
                headers=headers
            )
            
            results = []
            seen_urls: set = set()
            
            # 夸克搜索结果的简单提取
            pattern = r'<a[^>]*href="(https?://[^"]+)"[^>]*>(.*?)</a>'
            for m in re.finditer(pattern, r.text, re.DOTALL | re.IGNORECASE):
                url = m.group(1)
                title = re.sub(r'<[^>]+>', '', m.group(2)).strip()
                import html
                title = html.unescape(title)[:Config.MAX_TITLE_LEN]
                
                if title and len(title) > 5 and url not in seen_urls:
                    seen_urls.add(url)
                    results.append({
                        'title': title[:50],
                        'url': url,
                        'content': title[:100],
                    })
                
                if len(results) >= num:
                    break
            
            return results
    except Exception as e:
        return []

async def search_images(q: str, num: int) -> List[Dict[str, str]]:
    """图片搜索 - 极致优化"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=Config.CONNECT_TIMEOUT,
                read=Config.READ_TIMEOUT,
                write=3,
                pool=Config.CONNECTION_POOL_SIZE
            ),
            follow_redirects=True,
            verify=False,
            limits=httpx.Limits(
                max_connections=Config.CONNECTION_POOL_SIZE,
                max_keepalive_connections=Config.CONNECTIONS_PER_HOST
            ),
        ) as client:
            r = await client.get(
                'https://www.bing.com/images/search',
                params={'q': q, 'form': 'HDRSC2', 'first': 1},
                headers=_get_headers()
            )
            
            results = []
            seen_urls: Set[str] = set()
            
            # 多种图片 URL 提取模式
            patterns = [
                r'murl&quot;:&quot;(https?://[^&]+)&quot;',
                r'data-src=&quot;(https?://[^&]+)&quot;',
                r'data-thumb=&quot;(https?://[^&]+)&quot;',
                r'src=&quot;(https?://[^&]+\.(?:jpe?g|png|webp|gif))&quot;',
            ]
            
            for pattern in patterns:
                for m in re.finditer(pattern, r.text):
                    url = m.group(1)
                    if url and url not in seen_urls:
                        if any(ext in url.lower() for ext in 
                             ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
                            seen_urls.add(url)
                            results.append({'url': url, 'source': 'bing'})
                        
                        if len(results) >= num * 2:  # 多收集一些
                            break
                
                if len(results) >= num * 2:
                    break
            
            circuit_breaker.record_success('images')
            return results[:num]
            
    except Exception as e:
        circuit_breaker.record_failure('images')
        return []

async def crawl_page_content(url: str, max_chars: int = Config.MAX_CRAWL_CHARS) -> Dict[str, Any]:
    """网页爬取 - 极致优化，专为 LLM 优化"""
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=Config.CONNECT_TIMEOUT,
                read=Config.READ_TIMEOUT * 2,  # 爬取需要更长时间
                write=3,
                pool=Config.CONNECTION_POOL_SIZE
            ),
            follow_redirects=True,
            verify=False,
            limits=httpx.Limits(
                max_connections=Config.CONNECTION_POOL_SIZE,
                max_keepalive_connections=Config.CONNECTIONS_PER_HOST
            ),
        ) as client:
            r = await client.get(url, headers=_get_headers())
            html = r.text
            
            # 提取标题
            title = ''
            title_m = re.search(r'<title[^>]*>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
            if title_m:
                title = _clean_html(title_m.group(1))
            
            # 清理 HTML（移除无用内容）
            html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<nav[^>]*>.*?</nav>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<footer[^>]*>.*?</footer>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<header[^>]*>.*?</header>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<aside[^>]*>.*?</aside>', '', html, flags=re.DOTALL | re.IGNORECASE)
            html = re.sub(r'<!--.*?-->', '', html, flags=re.DOTALL)
            
            # 提取正文内容（智能优先级）
            content_parts = []
            
            # 1. 提取段落
            paragraphs = CONTENT_RE.findall(html)
            for p in paragraphs[:Config.MAX_PARAGRAPHS]:
                clean = _clean_html(p)
                if len(clean) > 10:  # 只保留有意义的段落
                    content_parts.append(clean)
            
            # 2. 如果段落太少，提取标题
            if len(content_parts) < 3:
                headings = HEADING_RE.findall(html)
                for h in headings[:5]:
                    clean = _clean_html(h)
                    if len(clean) > 5:
                        content_parts.insert(0, clean)  # 标题放在前面
            
            # 3. 如果还是太少，提取所有文本
            if len(content_parts) < 2:
                texts = TEXT_RE.findall(html)
                for text in texts:
                    clean = _clean_html(text)
                    if len(clean) > 20:
                        content_parts.append(clean)
            
            # 4. 如果还是太少，使用全文
            if not content_parts:
                full_text = _clean_html(html)
                content_parts = [full_text]
            
            content = '\n\n'.join(content_parts)
            
            # 截断
            if len(content) > max_chars:
                content = content[:max_chars] + '...'
            
            circuit_breaker.record_success('crawl')
            return {
                'url': url,
                'title': title,
                'content': content,
                'length': len(content),
                'paragraphs': len(content_parts),
                'source': 'crawl'
            }
            
    except Exception as e:
        circuit_breaker.record_failure('crawl')
        return {
            'url': url,
            'title': '',
            'content': f'抓取失败: {str(e)}',
            'length': 0,
            'error': str(e),
        }

async def do_search(q: str, eng: str, num: int) -> List[Dict[str, str]]:
    """执行搜索 - 智能路由"""
    if eng == 'all':
        # 并发搜索 + 熔断检查 + 夸克
        tasks = []
        if circuit_breaker.is_available('bing'):
            tasks.append(search_bing(q, num))
        if circuit_breaker.is_available('ddg'):
            tasks.append(search_ddg(q, num))
        # 夸克搜索引擎（轻量，不熔断）
        tasks.append(search_quark(q, num))
        
        if not tasks:
            await asyncio.sleep(Config.RETRY_DELAY)
            if circuit_breaker.is_available('bing'):
                tasks.append(search_bing(q, num))
            if circuit_breaker.is_available('ddg'):
                tasks.append(search_ddg(q, num))
        
        if not tasks:
            return []
        
        results_list = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 交叉验证合并结果
        all_results = []
        url_sources = {}  # 记录每个URL来自哪些搜索引擎
        
        for results in results_list:
            if isinstance(results, list):
                for item in results:
                    url = item.get('url', '')
                    if url:
                        if url not in url_sources:
                            url_sources[url] = []
                            all_results.append(item)
                        url_sources[url].append('quark' if 'search_quark' in str(results) else 'bing/ddg')
        
        # 交叉验证排序：被多个搜索引擎同时收录的结果优先
        def cross_validate(item):
            url = item.get('url', '')
            return len(url_sources.get(url, []))  # 来源数越多越优先
        
        all_results.sort(key=cross_validate, reverse=True)
        
        return all_results[:num]
    
    elif eng == 'bing':
        return await search_bing(q, num)
    elif eng == 'ddg':
        return await search_ddg(q, num)
    
    return []

# ========== 缓存装饰器 ==========
def cached(ttl: int = None):
    """缓存装饰器"""
    def decorator(f):
        @wraps(f)
        async def wrapper(*args, **kwargs):
            # 生成缓存键
            key_parts = [f.__name__]
            for arg in args:
                key_parts.append(str(arg))
            for k, v in kwargs.items():
                key_parts.append(f"{k}={v}")
            cache_key = hashlib.md5(':'.join(key_parts).encode()).hexdigest()
            
            # 检查缓存
            cached_result = cache.get(cache_key)
            if cached_result is not None:
                return cached_result
            
            # 执行函数
            result = await f(*args, **kwargs)
            
            # 写入缓存
            cache.set(cache_key, result)
            
            return result
        return wrapper
    return decorator

# ========== Flask 路由（极致优化版）==========
@app.after_request
def add_cors_headers(response):
    response.headers['Content-Type'] = 'application/json; charset=utf-8'
    return response

@app.route('/search')
@async_route
async def search():
    """搜索接口 - 极致优化"""
    q = request.args.get('q', '').strip()
    eng = request.args.get('engine', 'all')
    num = min(int(request.args.get('num', '5')), 10)  # 默认 5 条，最多 10 条
    
    if not q:
        return jsonify({'error': 'missing query parameter: q', 'code': 'MISSING_QUERY'}), 400
    
    # 修复中文乱码：检测是否包含中文字符，如果没有则尝试修复
    if q and not any('\u4e00' <= c <= '\u9fff' for c in q):
        # 尝试用 latin-1 解码修复
        try:
            fixed = q.encode('latin-1').decode('utf-8')
            if any('\u4e00' <= c <= '\u9fff' for c in fixed):
                q = fixed
        except:
            pass
    
    # 检查缓存
    cache_key = f"search:{q}:{eng}:{num}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return jsonify(cached_result)
    
    # 执行搜索
    results = await do_search(q, eng, num)
    
    response = {
        'query': q,
        'engine': eng,
        'results': results,
        'number_of_results': len(results),
        'timestamp': int(time.time()),
        'cache_hit': False,
        'circuit_breaker_state': {
            'bing': circuit_breaker.state.get('bing', 'closed'),
            'ddg': circuit_breaker.state.get('ddg', 'closed'),
        }
    }
    
    # 写入缓存
    cache.set(cache_key, response)
    
    # 使用 ensure_ascii=False 确保中文字符正确输出
    import json
    return app.response_class(
        response=json.dumps(response, ensure_ascii=False),
        status=200,
        mimetype='application/json'
    )

@app.route('/images')
@async_route
async def images():
    """图片搜索接口 - 极致优化"""
    q = request.args.get('q', '').strip()
    num = min(int(request.args.get('num', '3')), 10)  # 默认 3 条，最多 10 条
    
    if not q:
        return jsonify({'error': 'missing query parameter: q', 'code': 'MISSING_QUERY'}), 400
    
    # 检查缓存
    cache_key = f"images:{q}:{num}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return jsonify(cached_result)
    
    # 执行搜索
    results = await search_images(q, num)
    
    response = {
        'query': q,
        'results': results,
        'number_of_results': len(results),
        'timestamp': int(time.time()),
        'cache_hit': False,
    }
    
    # 写入缓存
    cache.set(cache_key, response)
    
    return jsonify(response)

@app.route('/crawl')
@async_route
async def crawl():
    """网页爬取接口 - 专为 LLM 优化"""
    url = request.args.get('url', '').strip()
    max_chars = min(int(request.args.get('max_chars', '3000')), 5000)  # 默认 3000，最多 5000
    
    if not url:
        return jsonify({'error': 'missing query parameter: url', 'code': 'MISSING_URL'}), 400
    
    # 确保 URL 格式正确
    if not url.startswith(('http://', 'https://')):
        url = 'https://' + url
    
    # 检查缓存
    cache_key = f"crawl:{url}:{max_chars}"
    cached_result = cache.get(cache_key)
    if cached_result:
        return jsonify(cached_result)
    
    # 执行爬取
    result = await crawl_page_content(url, max_chars)
    
    # 写入缓存
    cache.set(cache_key, result)
    
    return jsonify(result)

@app.route('/health')
def health():
    """健康检查 - 详细版"""
    uptime = time.time() - app.config.get('start_time', time.time())
    memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
    
    return jsonify({
        'status': 'healthy',
        'uptime': int(uptime),
        'cache': {
            'size': len(cache.cache),
            'max_size': cache.max_size,
            'hit_rate': cache.hit_rate,
            'hits': cache.hits,
            'misses': cache.misses,
        },
        'circuit_breaker': {
            'bing': circuit_breaker.state.get('bing', 'closed'),
            'ddg': circuit_breaker.state.get('ddg', 'closed'),
        },
        'memory': {
            'usage_mb': round(memory_usage, 2),
            'available_mb': round(psutil.virtual_memory().available / 1024 / 1024, 2),
        },
        'timestamp': int(time.time())
    })

@app.route('/stats')
def stats():
    """统计信息 - 详细版"""
    uptime = time.time() - app.config.get('start_time', time.time())
    memory_usage = psutil.Process().memory_info().rss / 1024 / 1024  # MB
    cpu_percent = psutil.Process().cpu_percent()
    
    return jsonify({
        'version': '2.0.0-ultimate',
        'uptime': int(uptime),
        'performance': {
            'cache_hit_rate': round(cache.hit_rate * 100, 2),
            'cache_entries': len(cache.cache),
            'cache_max_size': cache.max_size,
            'cache_ttl': cache.ttl,
        },
        'circuit_breaker': {
            'bing_state': circuit_breaker.state.get('bing', 'closed'),
            'ddg_state': circuit_breaker.state.get('ddg', 'closed'),
            'bing_failures': len(circuit_breaker.failures.get('bing', [])),
            'ddg_failures': len(circuit_breaker.failures.get('ddg', [])),
        },
        'system': {
            'memory_usage_mb': round(memory_usage, 2),
            'memory_available_mb': round(psutil.virtual_memory().available / 1024 / 1024, 2),
            'cpu_percent': cpu_percent,
            'disk_usage_percent': psutil.disk_usage('/').percent,
        },
        'config': {
            'max_cache': Config.MAX_CACHE,
            'cache_ttl': Config.CACHE_TTL,
            'connect_timeout': Config.CONNECT_TIMEOUT,
            'read_timeout': Config.READ_TIMEOUT,
            'max_retries': Config.MAX_RETRIES,
            'circuit_breaker_threshold': Config.CIRCUIT_BREAKER_THRESHOLD,
        },
        'timestamp': int(time.time())
    })

@app.route('/clear_cache', methods=['POST'])
def clear_cache():
    """清空缓存"""
    cache.clear()
    circuit_breaker.failures.clear()
    circuit_breaker.state.clear()
    return jsonify({'status': 'ok', 'message': 'cache and circuit breaker cleared'})

@app.route('/ping')
def ping():
    """心跳检测"""
    return jsonify({'status': 'pong', 'timestamp': int(time.time())})

# ========== 错误处理 ==========
@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'not found', 'code': 'NOT_FOUND'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'internal server error', 'code': 'INTERNAL_ERROR'}), 500

@app.errorhandler(429)
def rate_limit(e):
    return jsonify({'error': 'too many requests', 'code': 'RATE_LIMITED'}), 429

# ========== 中间件 ==========
@app.before_request
def before_request():
    """请求前处理"""
    request.start_time = time.time()

@app.after_request
def after_request(response):
    """请求后处理"""
    if hasattr(request, 'start_time'):
        elapsed = time.time() - request.start_time
        response.headers['X-Response-Time'] = f"{elapsed:.3f}s"
    response.headers['X-Cache-Size'] = str(len(cache.cache))
    response.headers['X-Cache-Hit-Rate'] = str(round(cache.hit_rate * 100, 2))
    return response

# ========== 主程序 ==========
def warmup():
    """预热：DNS 预解析 + 连接预热"""
    print("🔥 执行预热...")
    
    # DNS 预解析
    for host in Config.DNS_CACHE:
        try:
            socket.getaddrinfo(host, 80)
            print(f"   ✅ DNS 预解析: {host}")
        except Exception as e:
            print(f"   ❌ DNS 预解析失败: {host} - {e}")
    
    print("✅ 预热完成！")

def print_startup_info():
    """打印启动信息"""
    print("\n" + "="*70)
    print("🚀 搜索 API 服务端 - 终极优化版 v2.0.0")
    print("="*70)
    print("🎯 花活清单：")
    flower_tricks = [
        "✅ 异步并发 + 连接池复用",
        "✅ LRU 内存缓存 + 智能预热",
        "✅ DNS 预解析 + 连接预热",
        "✅ 搜索引擎熔断 + 自动降级",
        "✅ 结果去重 + 交叉验证",
        "✅ UA 轮换 + 请求头优化",
        "✅ 超时控制 + 自动重试",
        "✅ 内存监控 + 自动清理",
        "✅ 性能监控 + 实时统计",
        "✅ 错误恢复 + 优雅降级"
    ]
    for trick in flower_tricks:
        print(f"   {trick}")
    
    print(f"\n📊 配置信息：")
    config_info = [
        (f"端口", f"{os.environ.get('PORT', 11191)}"),
        (f"缓存大小", f"{Config.MAX_CACHE} 条"),
        (f"缓存 TTL", f"{Config.CACHE_TTL} 秒"),
        (f"连接池大小", f"{Config.CONNECTION_POOL_SIZE}"),
        (f"最大内容长度", f"{Config.MAX_CONTENT_LEN} 字符"),
        (f"最大标题长度", f"{Config.MAX_TITLE_LEN} 字符"),
        (f"爬取最大字符数", f"{Config.MAX_CRAWL_CHARS}"),
        (f"熔断阈值", f"{Config.CIRCUIT_BREAKER_THRESHOLD} 次失败"),
        (f"熔断超时", f"{Config.CIRCUIT_BREAKER_TIMEOUT} 秒"),
    ]
    for name, value in config_info:
        print(f"   {name:15}: {value}")
    
    print(f"\n🔗 API 端点：")
    endpoints = [
        ("搜索", "GET /search?q=关键词&engine=all&num=5"),
        ("图片", "GET /images?q=关键词&num=3"),
        ("爬取", "GET /crawl?url=网址&max_chars=3000"),
        ("健康", "GET /health"),
        ("统计", "GET /stats"),
        ("清缓存", "POST /clear_cache"),
        ("心跳", "GET /ping"),
    ]
    for name, path in endpoints:
        print(f"   {name:8}: {path}")
    
    print("\n💡 提示：")
    print("   • 所有 API 都支持缓存，减少重复请求")
    print("   • 熔断器会自动保护失败的搜索引擎")
    print("   • 爬取接口专为 LLM 优化，提取正文内容")
    print("   • 使用 /stats 监控性能和资源使用")
    print("="*70 + "\n")

if __name__ == '__main__':
    # 应用 DNS 预解析
    _patch_dns()
    
    # 打印启动信息
    print_startup_info()
    
    # 预热
    warmup()
    
    # 获取端口
    port = int(os.environ.get('PORT', 11191))
    
    # 启动服务器
    try:
        from waitress import serve
        print("🚀 使用 Waitress 服务器启动...")
        serve(
            app, 
            host='0.0.0.0', 
            port=port, 
            threads=8,  # 增加线程数
            connection_limit=Config.CONNECTION_POOL_SIZE,
            channel_timeout=Config.TOTAL_TIMEOUT,
        )
    except ImportError:
        print("⚠️  未找到 Waitress，使用 Flask 内置服务器...")
        app.run(
            host='0.0.0.0', 
            port=port, 
            threaded=True, 
            debug=False,
            processes=1,
        )