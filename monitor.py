import yaml
import requests
import feedparser
import json
import os
import re
import hashlib
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from googletrans import Translator
from email.utils import parsedate_to_datetime

# 配置常量
CONFIG_FILE = '_config.monitor.yml'
DATA_DIR = '_data/sitedata' 
MAX_HISTORY = 10 
TZ_SHANGHAI = pytz.timezone('Asia/Shanghai')

translator = Translator(service_urls=['translate.google.com', 'translate.google.cn'])

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

def format_date_str(date_input):
    """统一时间格式"""
    if not date_input or date_input == "未知时间":
        return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")
    try:
        dt = parsedate_to_datetime(date_input)
        return dt.astimezone(TZ_SHANGHAI).strftime("%Y-%m-%d %H:%M:%S")
    except:
        pass
    try:
        clean_date = re.sub(r'Published|at|on', '', date_input, flags=re.I).strip()
        for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(clean_date, fmt)
                return dt.strftime("%Y-%m-%d")
            except:
                continue
    except:
        pass
    return datetime.now(TZ_SHANGHAI).strftime("%Y-%m-%d")

def translate_if_needed(text):
    """翻译纯英文标题"""
    if not text: return text
    has_alpha = any(c.isalpha() for c in text)
    has_chinese = any('\u4e00' <= c <= '\u9fff' for c in text)
    if has_alpha and not has_chinese:
        try:
            result = translator.translate(text, dest='zh-cn')
            if result and result.text:
                return f"{result.text} ({text})"
        except:
            return f"[英] {text}"
    return text

def send_feishu_batch(webhook_url, site_name, new_items):
    """发送格式：标题 (时间)"""
    if not new_items: return
    post_content = []
    for item in new_items:
        post_content.append([
            {"tag": "a", "text": f"{item['title']}", "href": item['link']},
            {"tag": "text", "text": f" ({item['date']})\n"}
        ])
    data = {"msg_type": "post", "content": {"post": {"zh_cn": {"title": site_name, "content": post_content}}}}
    try:
        requests.post(webhook_url, json=data, timeout=15).raise_for_status()
    except Exception as e:
        print(f"❌ {site_name} 推送失败: {e}")

def get_storage_path(url):
    """优化 1：使用 URL 的 MD5 作为文件名避免冲突"""
    file_name = hashlib.md5(url.encode('utf-8')).hexdigest()
    return os.path.join(DATA_DIR, f"{file_name}.json")

def get_history(url):
    file_path = get_storage_path(url)
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try: return json.load(f)
            except: return []
    return []

def save_history(url, history_list):
    file_path = get_storage_path(url)
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)

# 执行任务
for task in config['tasks']:
    name, url = task['name'], task['url']
    webhook_url = os.environ.get(config['webhooks'].get(task['webhook']))
    if not webhook_url: continue

    print(f"🔍 检查中: {name}")
    try:
        current_list = []
        if task['type'] == 'rss':
            feed = feedparser.parse(url)
            for item in feed.entries[:MAX_HISTORY]:
                current_list.append({
                    "link": item.link,
                    "title": translate_if_needed(item.title),
                    "date": format_date_str(item.get('published', item.get('updated', '')))
                })
        else:
            resp = requests.get(url, timeout=30, headers={'User-Agent': 'Mozilla/5.0'})
            resp.encoding = task.get('force_encoding', 'utf-8')
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            elements = soup.select(task.get('selector'))[:MAX_HISTORY]
            for el in elements:
                # 优化 2：修复 hckr news 标题抓取错误
                # 优先寻找 class="link" 的 a 标签（hckr news 特征）
                link_el = el.select_one('a.link') or el.select_one('h2 a') or el.select_one('a')
                if not link_el: continue
                
                # 移除 source 标签内容（如 "(ccunpacked.dev)"），仅保留标题文字
                source_tag = link_el.select_one('.source')
                if source_tag: source_tag.decompose() 
                
                raw_title = link_el.get_text(strip=True)
                link = urljoin(url, link_el.get('href', ''))
                
                # 日期提取逻辑
                date_el = el.select_one('info b') or el.find(string=re.compile(r'[a-zA-Z]+ \d+, \d{4}'))
                raw_date = date_el.get_text(strip=True) if hasattr(date_el, 'get_text') else str(date_el)

                current_list.append({
                    "link": link,
                    "title": translate_if_needed(raw_title),
                    "date": format_date_str(raw_date)
                })

        if not current_list: continue

        old_history = get_history(url)
        old_links = {h['link'] for h in old_history}
        new_items = [item for item in current_list if item['link'] not in old_links]

        if new_items:
            send_feishu_batch(webhook_url, name, new_items)
            save_history(url, current_list)
            print(f"🚀 {name} 已发送 {len(new_items)} 条通知")
        else:
            print(f"✅ {name} 无新内容")

    except Exception as e:
        print(f"❌ {name} 任务失败: {e}")