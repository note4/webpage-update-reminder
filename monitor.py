import yaml
import requests
import feedparser
import json
import os
import re
from datetime import datetime
import pytz
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from googletrans import Translator
from email.utils import parsedate_to_datetime

# 配置文件名锁定
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
    """发送飞书通知"""
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

def get_storage_path(slug):
    """使用 slug 确定存储路径"""
    return os.path.join(DATA_DIR, f"{slug}.json")

# 执行任务
for task in config['tasks']:
    name = task['name']
    url = task['url']
    slug = task.get('slug') # 替换 dataname 为 slug
    
    # 强制要求配置 slug，否则跳过，防止乱生成文件名
    if not slug:
        print(f"⚠️ 跳过任务 [{name}]: 未在配置文件中指定 slug。")
        continue

    webhook_url = os.environ.get(config['webhooks'].get(task['webhook']))
    if not webhook_url: continue

    print(f"🔍 检查中: {name} (Slug: {slug})")
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
                # 1. 查找 a 標籤
                link_el = el.select_one('a.link') or el.select_one('h2 a') or el.select_one('a')
                if not link_el: continue
                
                # 2. 提取鏈接
                link = urljoin(url, link_el.get('href', ''))
                
                # 3. 提取標題 [兼容性修復]
                # 策略：優先取 title 屬性 -> 其次取內部的 h2 -> 最後取 a 標籤的純文本（排除摘要）
                raw_title = link_el.get('title', '').strip()
                
                if not raw_title:
                    h2_el = link_el.select_one('h2')
                    if h2_el:
                        raw_title = h2_el.get_text(strip=True)
                    else:
                        # 複製節點以剔除干擾標籤（如長沙地鐵的 em 摘要或 i 標籤）
                        temp_el = BeautifulSoup(str(link_el), 'html.parser').a
                        for noise in temp_el.select('.list_scontent, .source, em, i'):
                            noise.decompose()
                        raw_title = temp_el.get_text(strip=True)

                if not raw_title:
                    raw_title = "無標題"

                # 4. 提取日期 [兼容性修復]
                day_el = el.select_one('.listday')
                year_month_el = el.select_one('.listyear')
                
                if day_el and year_month_el:
                    # 針對長沙地鐵的拼接邏輯
                    date_str = f"{year_month_el.get_text(strip=True)}-{day_el.get_text(strip=True)}"
                else:
                    # 通用日期提取：尋找符合日期格式的標籤或文本
                    date_el = el.select_one('.date, .time, span[class*="date"]')
                    if date_el:
                        date_str = date_el.get_text(strip=True)
                    else:
                        # 正則匹配文本中的日期
                        date_search = el.find(string=re.compile(r'\d{4}[-/]\d{2}[-/]\d{2}'))
                        date_str = str(date_search) if date_search else ""

                current_list.append({
                    "link": link,
                    "title": translate_if_needed(raw_title),
                    "date": format_date_str(date_str)
                })

        if not current_list: continue

        # 基于 slug 获取历史记录
        file_path = get_storage_path(slug)
        old_links = set()
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                try:
                    old_data = json.load(f)
                    old_links = {h['link'] for h in old_data}
                except: pass

        new_items = [item for item in current_list if item['link'] not in old_links]

        if new_items:
            send_feishu_batch(webhook_url, name, new_items)
            # 保存新记录
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(current_list, f, ensure_ascii=False, indent=2)
            print(f"🚀 {name} 已更新 -> {slug}.json")
        else:
            print(f"✅ {name} 无新内容")

    except Exception as e:
        print(f"❌ {name} 任务失败: {e}")