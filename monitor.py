import yaml
import requests
import feedparser
import hashlib
import json
import os
import re
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# 路徑鎖定為 _data/sitedata
CONFIG_FILE = 'config_monitor.yml'
DATA_DIR = '_data/sitedata' 
MAX_HISTORY = 10 

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 加載配置文件
with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

def is_all_eng(text):
    """判斷是否為純英文標題"""
    return all(ord(c) < 128 for c in text) and any(c.isalpha() for c in text)

def translate_mock(text):
    """
    由於 googletrans 在 GitHub Actions 或本地易超時導致腳本卡死，
    建議僅在標題後標註 (English)。如需真翻譯，請確保環境可訪問 Google。
    """
    if is_all_eng(text):
        return f"[英] {text}"
    return text

def send_feishu(webhook_url, title, link):
    """發送飛書卡片消息"""
    data = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": "📢 更新通知",
                    "content": [
                        [{"tag": "text", "text": f"{title}\n"}],
                        [{"tag": "a", "text": "點擊查看原文", "href": link}]
                    ]
                }
            }
        }
    }
    try:
        r = requests.post(webhook_url, json=data, timeout=10)
        r.raise_for_status()
    except Exception as e:
        print(f"發送飛書失敗: {e}")

def get_history(task_name):
    """讀取該站點的歷史記錄列表"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                data = json.load(f)
                return data if isinstance(data, list) else []
            except: return []
    return []

def save_history(task_name, history_list):
    """保存更新後的歷史記錄列表"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)

for task in config['tasks']:
    name = task['name']
    url = task['url']
    env_name = config['webhooks'].get(task['webhook'])
    webhook_url = os.environ.get(env_name) if env_name else None
    
    if not webhook_url:
        print(f"⚠️ 任務 [{name}] 跳過：未找到環境變量 {env_name}")
        continue

    print(f"正在檢查: {name}")
    try:
        current_list = []
        if task['type'] == 'rss':
            # RSS 抓取前 10 條
            feed = feedparser.parse(url)
            for item in feed.entries[:MAX_HISTORY]:
                title = translate_mock(item.title)
                current_list.append({
                    "sign": item.get('id', item.link),
                    "title": title,
                    "link": item.link,
                    "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })
        else:
            # HTML 監測邏輯
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(url, timeout=20, headers=headers)
            resp.encoding = task.get('force_encoding', 'utf-8')
            soup = BeautifulSoup(resp.text, 'html.parser')
            
            selector = task.get('selector')
            if selector:
                # 獲取匹配選擇器的前 10 個節點
                elements = soup.select(selector)[:MAX_HISTORY]
                for el in elements:
                    # 關鍵修復：僅提取當前標籤內的直接文本，過濾子標籤（描述）
                    raw_title = el.find(text=True, recursive=False) or el.get_text(strip=True)
                    raw_title = raw_title.strip()
                    
                    # 處理長標題或混入描述的情況（截斷）
                    if len(raw_title) > 100: raw_title = raw_title[:100] + "..."
                    
                    title = translate_mock(raw_title)
                    link = urljoin(url, el['href']) if el.name == 'a' and el.get('href') else url
                    
                    current_list.append({
                        "sign": hashlib.md5((raw_title + link).encode('utf-8')).hexdigest(),
                        "title": title,
                        "link": link,
                        "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })

        if not current_list:
            print(f"❓ {name} 未抓取到內容，請檢查選擇器")
            continue

        # 讀取歷史數據
        old_history = get_history(name)
        old_top_sign = old_history[0]['sign'] if old_history else None
        new_top_sign = current_list[0]['sign']

        # 變動判斷：僅當最新一條發生變化時觸發通知，但更新全部 10 條數據
        if old_top_sign != new_top_sign:
            if old_top_sign is not None:
                print(f"🚀 {name} 檢測到新內容，發送通知")
                send_feishu(webhook_url, current_list[0]['title'], current_list[0]['link'])
            else:
                print(f"📝 {name} 初始數據已存入")
            
            # 保存最新的 10 條數據到 JSON
            save_history(name, current_list)
        else:
            print(f"✅ {name} 無變化")

    except Exception as e:
        print(f"❌ 任務 {name} 運行失敗: {e}")