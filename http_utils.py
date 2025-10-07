"""
HTTP 工具模块 - 独立实现
提供 HTTP 请求和 Cookie 管理功能
"""

import os
import requests
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter
from typing import Optional
from config import COOKIE_FILE, USER_AGENT


class CookieManager:
    """Cookie 管理器"""
    
    @staticmethod
    def read_cookie(path: str = COOKIE_FILE) -> str:
        """读取 Cookie 文件"""
        if not os.path.exists(path):
            return ""
        try:
            with open(path, "r", encoding='utf-8') as f:
                return f.read().strip()
        except Exception as e:
            print(f"读取 Cookie 失败: {e}")
            return ""
    
    @staticmethod
    def save_cookie(cookie: str, path: str = COOKIE_FILE):
        """保存 Cookie 到文件"""
        try:
            with open(path, "w", encoding='utf-8') as f:
                f.write(cookie)
            print(f"Cookie 已保存到 {path}")
        except Exception as e:
            print(f"保存 Cookie 失败: {e}")


class HTTPClient:
    """HTTP 客户端 - 带重试和 Session 管理"""
    
    def __init__(self):
        self.session = None
        self._init_session()
    
    def _init_session(self):
        """初始化 Session"""
        self.session = requests.Session()
        
        # 禁用代理（避免代理导致的连接问题）
        self.session.trust_env = False
        
        # 配置重试策略
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def get(self, url: str, use_cookie: bool = True) -> Optional[requests.Response]:
        """
        发送 GET 请求
        
        Args:
            url: 请求 URL
            use_cookie: 是否使用 Cookie
            
        Returns:
            Response 对象，失败返回 None
        """
        headers = {'User-Agent': USER_AGENT}
        
        if use_cookie:
            cookie = CookieManager.read_cookie()
            if cookie:
                headers['Cookie'] = cookie
        
        try:
            response = self.session.get(url, headers=headers, timeout=30)
            return response
        except requests.exceptions.ProxyError as e:
            print(f"\n❌ 代理错误: {e}")
            print("💡 解决方法:")
            print("   1. 关闭系统代理")
            print("   2. 或设置环境变量: set HTTP_PROXY= 和 set HTTPS_PROXY=")
            print("   3. 或检查代理软件设置\n")
            return None
        except requests.exceptions.SSLError as e:
            print(f"\n❌ SSL 证书错误: {e}")
            print("💡 解决方法:")
            print("   1. 检查网络连接")
            print("   2. 关闭 VPN 或代理")
            print("   3. 确保系统时间正确\n")
            return None
        except requests.exceptions.Timeout as e:
            print(f"\n❌ 请求超时: {e}")
            print("💡 解决方法:")
            print("   1. 检查网络连接")
            print("   2. 稍后重试\n")
            return None
        except requests.exceptions.RequestException as e:
            print(f"\n❌ 请求失败: {e}")
            print("💡 请检查网络连接\n")
            return None
    
    def close(self):
        """关闭 Session"""
        if self.session:
            self.session.close()


# 全局 HTTP 客户端实例
_http_client = None


def get_http_client() -> HTTPClient:
    """获取全局 HTTP 客户端实例"""
    global _http_client
    if _http_client is None:
        _http_client = HTTPClient()
    return _http_client

