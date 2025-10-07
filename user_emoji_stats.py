"""
水源社区用户 Emoji 统计工具 - 独立模块
爬取指定用户的所有发言，统计其中使用的 emoji
"""

import json
import re
import os
from typing import Dict, List, Optional
from datetime import datetime
from collections import Counter
from bs4 import BeautifulSoup

from config import USER_ACTIONS_API, SHUIYUAN_BASE, OUTPUT_DIR, ITEMS_PER_PAGE
from http_utils import get_http_client

_invalid_fname = re.compile(r"[^A-Za-z0-9._-]+")

def safe_filename(name: str) -> str:
    return _invalid_fname.sub("_", name.strip()) or "user"

def window_suffix(since: Optional[str], until: Optional[str]) -> str:
    def fmt(d: Optional[str]) -> Optional[str]:
        if not d:
            return None
        dt = parse_iso_datetime(d)
        if not dt:
            return None
        # 输出到日级即可
        return dt.strftime('%Y%m%d')
    s, u = fmt(since), fmt(until)
    if s and u:
        return f"_{s}_to_{u}"
    if s:
        return f"_{s}_to_"
    if u:
        return f"__to_{u}"
    return ""


def parse_iso_datetime(dt_str: str) -> Optional[datetime]:
    try:
        # Discourse 返回类似 2024-05-12T03:14:15.000Z
        return datetime.strptime(dt_str.replace('Z', '+0000'), '%Y-%m-%dT%H:%M:%S.%f%z')
    except Exception:
        try:
            return datetime.strptime(dt_str.replace('Z', '+0000'), '%Y-%m-%dT%H:%M:%S%z')
        except Exception:
            return None


def get_user_replies(username: str, max_pages: int = None,
                     since_dt: Optional[datetime] = None,
                     until_dt: Optional[datetime] = None) -> List[Dict]:
    """
    获取指定用户的所有回复
    
    Args:
        username: 用户名
        max_pages: 最大页数，None 表示获取所有
        
    Returns:
        回复列表
    """
    print(f'正在获取用户 @{username} 的回复...')
    
    http_client = get_http_client()
    all_replies = []
    offset = 0
    page = 1
    
    while True:
        if max_pages and page > max_pages:
            break
            
        # filter=5 表示 replies (回复)
        url = f"{USER_ACTIONS_API}?username={username}&filter=5&offset={offset}"
        
        try:
            response = http_client.get(url)
            
            if not response or response.status_code != 200:
                print(f"请求失败: {response.status_code if response else 'Network Error'}")
                break
                
            data = json.loads(response.text)
            user_actions = data.get('user_actions', [])
            
            if not user_actions:
                print(f"已获取所有回复，共 {len(all_replies)} 条")
                break
                
            # 过滤时间窗口（within-page）
            filtered_actions: List[Dict] = []
            page_times: List[datetime] = []
            for ua in user_actions:
                c = ua.get('created_at')
                cdt = parse_iso_datetime(c) if c else None
                if cdt:
                    page_times.append(cdt)
                # 应用窗口：since <= cdt <= until
                if cdt:
                    if since_dt and cdt < since_dt:
                        continue
                    if until_dt and cdt > until_dt:
                        continue
                filtered_actions.append(ua)

            all_replies.extend(filtered_actions)
            print(f"第 {page} 页: 获取了 {len(user_actions)} 条，窗口内 {len(filtered_actions)} 条 (累计 {len(all_replies)} 条)")

            # 提前停止条件：页面最老时间 < since_dt（后续只会更老）
            if since_dt and page_times:
                oldest_on_page = min(page_times)
                if oldest_on_page < since_dt:
                    print("达到开始时间阈值，停止翻页。")
                    break
            
            offset += ITEMS_PER_PAGE
            page += 1
            
        except Exception as e:
            print(f"获取第 {page} 页时出错: {e}")
            break
    
    return all_replies


def extract_emoji_from_html(html_content: str) -> List[str]:
    """
    从 HTML 内容中提取所有 emoji
    支持: Unicode emoji、Discourse 短代码、HTML img 标签
    
    Args:
        html_content: HTML 内容
        
    Returns:
        emoji 列表
    """
    emojis = []
    
    if not html_content:
        return emojis
    
    # 1.（禁用）不再提取 Unicode emoji，严格限定为 :lowercase_with_underscores: 短代码
    
    # 2. 提取 Discourse 短代码 :emoji_name:
    # 严格匹配：只包含小写英文字母和下划线
    # 从 HTML 标签的 title 或 alt 属性中提取
    # 例如：title=":yaoming:" 或 alt=":smiling_face_with_three_hearts:"
    img_emoji_pattern = re.compile(r'(?:title|alt)="(:([a-z_]+):)"')
    img_emojis = img_emoji_pattern.findall(html_content)
    # 提取匹配到的 emoji 短代码（带冒号的完整形式）
    # 只保留长度在 2-50 之间的
    emoji_shortcodes = [match[0] for match in img_emojis if 2 <= len(match[1]) <= 50]
    emojis.extend(emoji_shortcodes)

    # 2.1 直接从文本中严格匹配形如 :lowercase_with_underscores: 的短代码
    text_shortcode_pattern = re.compile(r':([a-z_]{2,50}):')
    text_shortcodes = [f':{code}:' for code in text_shortcode_pattern.findall(html_content)]
    emojis.extend(text_shortcodes)
    
    # 3. 提取 HTML img 标签中的 emoji（作为补充）
    try:
        soup = BeautifulSoup(html_content, 'html.parser')
        emoji_imgs = soup.find_all('img', class_='emoji')
        for img in emoji_imgs:
            emoji_name = img.get('title') or img.get('alt')
            if emoji_name:
                # 去掉冒号，提取 emoji 名称
                emoji_clean = emoji_name.strip(':')
                # 严格过滤：只保留小写字母和下划线组成的名称
                if emoji_clean and re.match(r'^[a-z_]+$', emoji_clean) and 2 <= len(emoji_clean) <= 50:
                    emojis.append(f':{emoji_clean}:')
    except Exception as e:
        pass  # HTML 解析失败不影响整体
    
    # 最终统一严格过滤，避免任何非规范内容混入
    final_filter = re.compile(r'^:[a-z_]{2,50}:$')
    return [e[1:-1] for e in emojis if final_filter.match(e)]


def analyze_user_emojis(username: str, max_pages: int = None, 
                        since: Optional[str] = None, until: Optional[str] = None) -> Dict:
    """
    分析指定用户的 emoji 使用情况
    
    Args:
        username: 用户名
        max_pages: 最大页数
        
    Returns:
        统计结果字典
    """
    # 获取用户所有回复（带窗口的翻页优化）
    replies = get_user_replies(username, max_pages,
                               since_dt=parse_iso_datetime(since) if since else None,
                               until_dt=parse_iso_datetime(until) if until else None)
    
    if not replies:
        print(f"未找到用户 @{username} 的回复")
        return {}
    
    print(f'\n开始分析 emoji...')
    
    # 统计数据
    all_emojis = []
    post_with_emoji = 0
    emoji_by_topic = {}
    
    # 时间窗口解析
    since_dt = parse_iso_datetime(since) if since else None
    until_dt = parse_iso_datetime(until) if until else None

    for i, reply in enumerate(replies):
        # 时间过滤
        created_at = reply.get('created_at')
        created_dt = parse_iso_datetime(created_at) if created_at else None
        if since_dt and created_dt and created_dt < since_dt:
            continue
        if until_dt and created_dt and created_dt > until_dt:
            continue
        # 尝试多个可能包含内容的字段
        cooked = reply.get('cooked', '')
        excerpt = reply.get('excerpt', '')
        
        # 如果 cooked 为空，尝试使用 excerpt
        content = cooked if cooked else excerpt
        
        emojis_in_post = extract_emoji_from_html(content)
        
        if emojis_in_post:
            post_with_emoji += 1
            all_emojis.extend(emojis_in_post)
            
            # 按话题分类
            topic_id = reply.get('topic_id')
            topic_title = reply.get('title', f'Topic {topic_id}')
            if topic_id not in emoji_by_topic:
                emoji_by_topic[topic_id] = {
                    'title': topic_title,
                    'emojis': []
                }
            emoji_by_topic[topic_id]['emojis'].extend(emojis_in_post)
    
    # 统计频率
    emoji_counter = Counter(all_emojis)
    
    # 生成结果
    result = {
        'username': username,
        'total_replies': len(replies),
        'replies_with_emoji': post_with_emoji,
        'emoji_usage_rate': f"{post_with_emoji / len(replies) * 100:.2f}%" if replies else "0%",
        'total_emojis': len(all_emojis),
        'unique_emojis': len(emoji_counter),
        'emoji_frequency': dict(emoji_counter.most_common()),
        'top_10_emojis': emoji_counter.most_common(10),
        'emoji_by_topic': emoji_by_topic,
        'since': since,
        'until': until
    }
    
    # 打印统计摘要
    print_statistics(result)
    
    # 保存结果
    save_results(result)
    
    return result


def print_statistics(result: Dict):
    """打印统计结果摘要"""
    print("\n" + "="*60)
    print(f"用户 @{result['username']} 的 Emoji 使用统计")
    print("="*60)
    print(f"总回复数: {result['total_replies']}")
    print(f"包含 Emoji 的回复数: {result['replies_with_emoji']}")
    print(f"Emoji 使用率: {result['emoji_usage_rate']}")
    print(f"Emoji 总数: {result['total_emojis']}")
    print(f"不同 Emoji 种类: {result['unique_emojis']}")
    
    print("\n" + "-"*60)
    print("Top 10 最常用 Emoji:")
    print("-"*60)
    for i, (emoji, count) in enumerate(result['top_10_emojis'], 1):
        percentage = count / result['total_emojis'] * 100 if result['total_emojis'] > 0 else 0
        print(f"{i:2d}. {emoji:20s} : {count:4d} 次 ({percentage:5.2f}%)")
    
    print("="*60 + "\n")


def get_emoji_path(emoji:str)->str:
    """根据 emoji 名称获取本地图片路径"""
    from itertools import chain 
    if os.path.exists(f"emoji/{emoji}.png"):
        return f"emoji/{emoji}.png"
    with open("emojis.json","r",encoding="UTF-8") as file:
        data = json.load(file)
    
    for i in chain(data["公司"],data["软件服务"],data["default"],data["游戏"],data["学校"],data["编程语言"]):
        if i["name"] == emoji:
            path="emoji/"+i["url"][32:]
            break
    return path

def save_results(result: Dict):
    """保存统计结果到文件"""
    username = result['username']
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    # 生成 Top10 柱状图
    try:
        from matplotlib import pyplot as plt
        from matplotlib.offsetbox import OffsetImage, AnnotationBbox
        import matplotlib.image as mpimg
        import numpy as np


        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei"]
        plt.rcParams["axes.unicode_minus"]=False
        top10 = result['top_10_emojis']
        if top10:
            emojis = [e for e,_ in top10]
            counts = [c for _,c in top10]
            emoji_paths=[]
            for i in emojis:
                emoji_paths.append(get_emoji_path(i))

            fig, ax = plt.subplots(figsize=(16, 9))
            x_pos = np.arange(len(emojis))
            bars = ax.bar(x_pos, counts, 
                        color='#1DA1F2',
                        alpha=0.75)
            
            ax.set_ylabel('Counts')
            ax.set_title(f'Top 10 Emojis for @{username}')
            ax.set_ylim(0, max(counts)*1.1)
            ax.set_xticks([])
            
            for i, (emoji, count) in enumerate(zip(emojis, counts)):
                if os.path.exists(emoji_paths[i]):
                    try:
                        from PIL import Image

                        #预处理图片：调整大小、背景透明等
                        img = Image.open(emoji_paths[i])
                        img=img.convert("RGBA")
                        original_width, original_height = img.size
                        ratio = 100 / original_height
                        new_width = int(original_width * ratio)
                        img = img.resize((new_width,100),Image.Resampling.LANCZOS)
                        # 使用imshow显示图片，需要计算合适的位置和大小
                        imagebox = OffsetImage(img, zoom=0.25)
                        ab = AnnotationBbox(imagebox, (i, 0),
                                        xycoords='data',
                                        frameon=False,
                                        box_alignment=(0.5, 1))
                        ax.add_artist(ab)
                    except Exception as e:
                        print(f"无法加载logo {emoji_paths[i]}: {e}")
                
                # 添加两行文字
                # 第一行：表情符号
                ax.text(i,  -1, emoji, 
                    ha='center', va='top', fontsize=8)
                
                # 第二行：计数
                ax.text(i,  -1.5, f"{count}", 
                    ha='center', va='top', fontsize=11, color='gray')
                        
            fname_user = safe_filename(username)
            chart_path = f"{OUTPUT_DIR}/{fname_user}_top10{window_suffix(result.get('since'), result.get('until'))}.png"

            plt.show()
            plt.savefig(chart_path, dpi=150)
            plt.close()
        else:
            chart_path = None
    except Exception as e:
        chart_path = None
        print(e)

    # 保存 JSON
    fname_user = safe_filename(username)
    json_path = f"{OUTPUT_DIR}/{fname_user}_emoji_stats{window_suffix(result.get('since'), result.get('until'))}.json"
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    # 保存 Markdown 报告
    md_path = f"{OUTPUT_DIR}/{fname_user}_emoji_report{window_suffix(result.get('since'), result.get('until'))}.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(f"# 用户 @{username} 的 Emoji 使用报告\n\n")
        
        f.write("## 统计概览\n\n")
        f.write(f"- **总回复数**: {result['total_replies']}\n")
        f.write(f"- **包含 Emoji 的回复数**: {result['replies_with_emoji']}\n")
        f.write(f"- **Emoji 使用率**: {result['emoji_usage_rate']}\n")
        f.write(f"- **Emoji 总数**: {result['total_emojis']}\n")
        f.write(f"- **不同 Emoji 种类**: {result['unique_emojis']}\n\n")
        if result.get('since') or result.get('until'):
            f.write("### 时间窗口\n\n")
            f.write(f"- since: {result.get('since') or '-'}\n")
            f.write(f"- until: {result.get('until') or '-'}\n\n")
        
        f.write("## Top 10 最常用 Emoji\n\n")
        f.write("| 排名 | Emoji | 使用次数 | 占比 |\n")
        f.write("|------|-------|----------|------|\n")
        for i, (emoji, count) in enumerate(result['top_10_emojis'], 1):
            percentage = count / result['total_emojis'] * 100 if result['total_emojis'] > 0 else 0
            f.write(f"| {i} | {emoji} | {count} | {percentage:.2f}% |\n")
        if chart_path:
            f.write("\n![Top 10 Emojis](" + chart_path.replace('\\\\', '/') + ")\n\n")
        
        f.write("\n## 完整 Emoji 使用频率\n\n")
        f.write("| Emoji | 使用次数 | 占比 |\n")
        f.write("|-------|----------|------|\n")
        for emoji, count in sorted(result['emoji_frequency'].items(), 
                                   key=lambda x: x[1], reverse=True):
            percentage = count / result['total_emojis'] * 100 if result['total_emojis'] > 0 else 0
            f.write(f"| {emoji} | {count} | {percentage:.2f}% |\n")
        
        f.write("\n## 按话题统计\n\n")
        for topic_id, data in result['emoji_by_topic'].items():
            emoji_count = len(data['emojis'])
            if emoji_count > 0:
                f.write(f"### [{data['title']}]({SHUIYUAN_BASE}t/topic/{topic_id})\n\n")
                f.write(f"- Emoji 总数: {emoji_count}\n")
                topic_counter = Counter(data['emojis'])
                f.write(f"- 不同 Emoji: {len(topic_counter)}\n")
                f.write(f"- Top 5: {', '.join([f'{e}({c})' for e, c in topic_counter.most_common(5)])}\n\n")
    
    print(f"\n统计结果已保存:")
    print(f"  - JSON: {json_path}")
    print(f"  - Markdown: {md_path}")


def batch_analyze_users(usernames: List[str], max_pages: int = None):
    """批量分析多个用户"""
    results = {}
    
    for i, username in enumerate(usernames, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(usernames)}] 正在分析用户: @{username}")
        print(f"{'='*60}\n")
        
        try:
            result = analyze_user_emojis(username, max_pages)
            results[username] = result
        except Exception as e:
            print(f"分析用户 @{username} 时出错: {e}")
            continue
    
    # 生成对比报告
    if len(results) > 1:
        generate_comparison_report(results)
    
    return results


def generate_comparison_report(results: Dict[str, Dict]):
    """生成多用户对比报告"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    md_path = f"{OUTPUT_DIR}/comparison_report.md"
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write("# 多用户 Emoji 使用对比报告\n\n")
        
        f.write("## 用户概览\n\n")
        f.write("| 用户名 | 总回复数 | 含Emoji回复 | 使用率 | Emoji总数 | 不同种类 |\n")
        f.write("|--------|----------|-------------|--------|-----------|----------|\n")
        
        for username, result in results.items():
            f.write(f"| @{username} | {result['total_replies']} | "
                   f"{result['replies_with_emoji']} | {result['emoji_usage_rate']} | "
                   f"{result['total_emojis']} | {result['unique_emojis']} |\n")
        
        f.write("\n## 各用户 Top 5 Emoji\n\n")
        for username, result in results.items():
            f.write(f"### @{username}\n\n")
            for i, (emoji, count) in enumerate(result['top_10_emojis'][:5], 1):
                f.write(f"{i}. {emoji} ({count}次)  \n")
            f.write("\n")
    
    print(f"\n对比报告已保存: {md_path}")


if __name__ == "__main__":
    import argparse
    from http_utils import CookieManager
    import os
    import webbrowser
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog
    try:
        from tkcalendar import DateEntry
        _tkcalendar_ok = True
    except Exception:
        _tkcalendar_ok = False
    from datetime import timezone
    
    parser = argparse.ArgumentParser(
        description="统计水源社区用户的 Emoji 使用情况"
    )
    parser.add_argument(
        'username', 
        type=str, 
        nargs='?',
        help='要分析的用户名（例如: krm_desuwa）'
    )
    parser.add_argument(
        '-b', '--batch',
        nargs='+',
        type=str,
        help='批量分析多个用户'
    )
    parser.add_argument(
        '-p', '--max-pages',
        type=int,
        default=None,
        help='最大分析页数（默认: 全部）'
    )
    parser.add_argument(
        '--since',
        type=str,
        default=None,
        help='开始时间 (ISO8601, 如 2024-01-01T00:00:00Z)'
    )
    parser.add_argument(
        '--until',
        type=str,
        default=None,
        help='结束时间 (ISO8601, 如 2024-12-31T23:59:59Z)'
    )
    parser.add_argument(
        '--set-cookie',
        type=str,
        help='设置 Cookie'
    )
    # 移除调试参数，保持界面与 CLI 简洁
    parser.add_argument(
        '--gui',
        action='store_true',
        help='启动图形界面 (Tkinter)'
    )
    
    args = parser.parse_args()
    
    # 设置 Cookie
    if args.set_cookie:
        CookieManager.save_cookie(args.set_cookie)
        print("Cookie 已保存")
        exit(0)
    
    # 检查 Cookie
    cookie_string = CookieManager.read_cookie()
    if not cookie_string and not args.gui:
        print("⚠️  警告: 未找到 Cookie 文件")
        print("请使用 --set-cookie 'YOUR_COOKIE' 设置 Cookie")
        print("或创建 cookies.txt 文件并粘贴 Cookie 内容")
        exit(1)
    
    # 执行分析
    if args.gui:
        # 简单 GUI（按天选择）
        def run_gui():
            root = tk.Tk()
            root.title("Emoji 统计工具")
            root.geometry("620x420")
            try:
                root.tk.call("tk", "scaling", 1.25)
            except Exception:
                pass

            style = ttk.Style()
            try:
                style.theme_use('clam')
            except Exception:
                pass
            style.configure('TButton', padding=6)
            style.configure('TLabel', padding=4)
            style.configure('TEntry', padding=4)

            main = ttk.Frame(root, padding=20)
            main.pack(fill=tk.BOTH, expand=True)

            # 用户名
            ttk.Label(main, text="用户名:").grid(row=0, column=0, sticky=tk.W)
            username_var = tk.StringVar()
            username_entry = ttk.Entry(main, textvariable=username_var, width=32)
            username_entry.grid(row=0, column=1, columnspan=2, sticky=tk.W)

            # since/until（按天，日历选择器优先）
            ttk.Label(main, text="开始日期:").grid(row=1, column=0, sticky=tk.W)
            ttk.Label(main, text="结束日期:").grid(row=2, column=0, sticky=tk.W)
            since_var = tk.StringVar()
            until_var = tk.StringVar()

            if _tkcalendar_ok:
                since_picker = DateEntry(main, date_pattern='yyyy-mm-dd', width=14)
                until_picker = DateEntry(main, date_pattern='yyyy-mm-dd', width=14)
                since_picker.grid(row=1, column=1, sticky=tk.W)
                until_picker.grid(row=2, column=1, sticky=tk.W)
                ttk.Label(main, text="(可留空)").grid(row=1, column=2, sticky=tk.W)
                ttk.Label(main, text="(可留空)").grid(row=2, column=2, sticky=tk.W)
            else:
                since_entry = ttk.Entry(main, textvariable=since_var, width=16)
                since_entry.grid(row=1, column=1, sticky=tk.W)
                until_entry = ttk.Entry(main, textvariable=until_var, width=16)
                until_entry.grid(row=2, column=1, sticky=tk.W)
                ttk.Label(main, text="YYYY-MM-DD (可留空)").grid(row=1, column=2, sticky=tk.W)
                ttk.Label(main, text="YYYY-MM-DD (可留空)").grid(row=2, column=2, sticky=tk.W)

            # 页数限制
            ttk.Label(main, text="最大页数 (可选):").grid(row=3, column=0, sticky=tk.W)
            max_pages_var = tk.StringVar()
            max_pages_entry = ttk.Entry(main, textvariable=max_pages_var, width=8)
            max_pages_entry.grid(row=3, column=1, sticky=tk.W)

            # 状态
            status_var = tk.StringVar(value="准备就绪…")
            status_label = ttk.Label(main, textvariable=status_var)
            status_label.grid(row=6, column=0, columnspan=3, sticky=tk.W, pady=(12,0))

            def to_iso_day(day_str: str, end=False):
                if not day_str:
                    return None
                try:
                    # 基础校验：YYYY-MM-DD
                    if not re.match(r'^\d{4}-\d{2}-\d{2}$', day_str):
                        messagebox.showwarning("提示", "日期格式应为 YYYY-MM-DD")
                        return None
                    dt = datetime.strptime(day_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                    if end:
                        # 结束日设为当天 23:59:59
                        dt = dt.replace(hour=23, minute=59, second=59)
                    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
                except Exception:
                    messagebox.showwarning("提示", "请输入有效的日期")
                    return None

            def on_run():
                username = username_var.get().strip()
                if not username:
                    messagebox.showwarning("提示", "请输入用户名")
                    return

                if _tkcalendar_ok:
                    s = since_picker.get_date() if since_picker.get() else None
                    u = until_picker.get_date() if until_picker.get() else None
                    since_iso = to_iso_day(s.strftime('%Y-%m-%d') if s else '', end=False)
                    until_iso = to_iso_day(u.strftime('%Y-%m-%d') if u else '', end=True)
                else:
                    since_iso = to_iso_day(since_var.get().strip(), end=False)
                    until_iso = to_iso_day(until_var.get().strip(), end=True)

                max_pages = None
                mp_raw = max_pages_var.get().strip()
                if mp_raw:
                    if mp_raw.isdigit():
                        max_pages = int(mp_raw)
                    else:
                        messagebox.showwarning("提示", "最大页数应为正整数，将忽略该值")

                # 若无 cookie，引导设置
                if not CookieManager.read_cookie():
                    messagebox.showwarning("提示", "未找到 Cookie，请先配置 cookies.txt 或使用 --set-cookie 运行命令行设置。")
                    return

                status_var.set("正在分析… 这可能需要一些时间")
                root.update_idletasks()
                try:
                    res = analyze_user_emojis(username, max_pages=max_pages,
                                              since=since_iso, until=until_iso)
                    status_var.set("完成！点击“打开输出目录”查看结果")
                except Exception as e:
                    messagebox.showerror("错误", str(e))
                    status_var.set("发生错误")

            def on_open_dir():
                try:
                    out_dir = os.path.abspath(OUTPUT_DIR)
                    if os.path.exists(out_dir):
                        webbrowser.open(out_dir)
                    else:
                        messagebox.showinfo("提示", "尚未生成输出目录")
                except Exception as e:
                    messagebox.showerror("错误", str(e))

            # 快捷时间范围按钮
            quick_frame = ttk.Frame(main)
            quick_frame.grid(row=4, column=0, columnspan=3, pady=8, sticky=tk.W)

            def quick_range(days: int = None, mode: str = None):
                from datetime import timedelta
                now = datetime.now(timezone.utc)
                if days is not None:
                    start = (now - timedelta(days=days)).date()
                    end = now.date()
                elif mode == 'month':
                    start = now.replace(day=1).date()
                    end = now.date()
                elif mode == 'year':
                    start = now.replace(month=1, day=1).date()
                    end = now.date()
                else:
                    return
                if _tkcalendar_ok:
                    since_picker.set_date(start)
                    until_picker.set_date(end)
                else:
                    since_var.set(start.strftime('%Y-%m-%d'))
                    until_var.set(end.strftime('%Y-%m-%d'))

            ttk.Button(quick_frame, text="最近7天", command=lambda: quick_range(days=7)).grid(row=0, column=0, padx=(0,8))
            ttk.Button(quick_frame, text="最近30天", command=lambda: quick_range(days=30)).grid(row=0, column=1, padx=(0,8))
            ttk.Button(quick_frame, text="本月", command=lambda: quick_range(mode='month')).grid(row=0, column=2, padx=(0,8))
            ttk.Button(quick_frame, text="今年", command=lambda: quick_range(mode='year')).grid(row=0, column=3, padx=(0,8))

            # 操作按钮
            btn_frame = ttk.Frame(main)
            btn_frame.grid(row=5, column=0, columnspan=3, pady=8, sticky=tk.W)
            ttk.Button(btn_frame, text="开始分析", command=on_run).grid(row=0, column=0, padx=(0,8))
            ttk.Button(btn_frame, text="打开输出目录", command=on_open_dir).grid(row=0, column=1)

            for i in range(3):
                main.grid_columnconfigure(i, weight=1)

            root.mainloop()

        run_gui()
        exit(0)

    if args.batch:
        batch_analyze_users(args.batch, args.max_pages)
    elif args.username:
        analyze_user_emojis(args.username, args.max_pages,
                            since=args.since, until=args.until)
    else:
        # 交互模式
        print("="*60)
        print("水源社区用户 Emoji 统计工具")
        print("="*60)
        username = input("\n请输入要分析的用户名: ").strip()
        if username:
            since = input("请输入开始时间(ISO8601, 回车跳过): ").strip() or None
            until = input("请输入结束时间(ISO8601, 回车跳过): ").strip() or None
            analyze_user_emojis(username, since=since, until=until)
        else:
            print("未输入用户名，退出。")
