"""
配置文件 - 独立模块
包含 API 端点和常量定义
"""

# 水源社区 API 端点
SHUIYUAN_BASE = "https://shuiyuan.sjtu.edu.cn/"
USER_ACTIONS_API = SHUIYUAN_BASE + "user_actions.json"

# HTTP 配置
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'

# Cookie 文件路径
COOKIE_FILE = "./cookies.txt"

# 输出目录
OUTPUT_DIR = "./emoji_stats_output"

# 分页配置
ITEMS_PER_PAGE = 30  # Discourse API 默认每页30条

