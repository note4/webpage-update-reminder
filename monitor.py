import yaml
import requests
import feedparser
import hashlib
import json
import os
from datetime import datetime

# 配置常量
CONFIG_FILE = 'config_monitor.yml'
DATA_DIR = '_data/sitedata'  # 适配 Jekyll 自动读取路径
MAX_HISTORY = 10             # 每个站点保留最近10条

if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)

def send_feishu(webhook_url, title, content, link):
    """发送飞书卡片消息"""
    data = {
        "msg_type": "post",
        "content": {
            "post": {
                "zh_cn": {
                    "title": f"📢 更新通知: {title}",
                    "content": [
                        [{"tag": "text", "text": f"{content}\n"}],
                        [{"tag": "a", "text": "点击查看原文", "href": link}]
                    ]
                }
            }
        }
    }
    try:
        r = requests.post(webhook_url, json=data)
        r.raise_for_status()
    except Exception as e:
        print(f"发送飞书失败: {e}")

def get_history(task_name):
    """读取该站点的历史记录列表"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f)
            except:
                return []
    return []

def save_history(task_name, history_list):
    """保存更新后的历史记录列表"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(history_list, f, ensure_ascii=False, indent=2)

for task in config['tasks']:
    name = task['name']
    url = task['url']
    env_name = config['webhooks'].get(task['webhook'])
    webhook_url = os.environ.get(env_name) if env_name else None
    
    if not webhook_url:
        print(f"⚠️ 任务 [{name}] 跳过：未找到环境变量 {env_name}")
        continue

    print(f"正在检查: {name}")
    try:
        current_entry = {}
        if task['type'] == 'rss':
            feed = feedparser.parse(url)
            if not feed.entries: continue
            item = feed.entries[0]
            current_entry = {
                "sign": item.get('id', item.link),
                "title": item.title,
                "link": item.link,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        else:
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(url, timeout=30, headers=headers)
            resp.encoding = task.get('force_encoding', 'utf-8')
            current_entry = {
                "sign": hashlib.md5(resp.text.encode('utf-8')).hexdigest(),
                "title": "网页内容发生变动",
                "link": url,
                "date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }

        # 获取历史记录列表
        history = get_history(name)
        old_sign = history[0]['sign'] if history else None

        if old_sign != current_entry['sign']:
            # 1. 发送飞书通知 (仅在非第一次运行时)
            if old_sign is not None:
                print(f"🚀 {name} 有更新，发送通知")
                send_feishu(webhook_url, name, current_entry['title'], current_entry['link'])
            else:
                print(f"📝 {name} 初始记录成功")
            
            # 2. 更新历史列表并保持10条记录
            history.insert(0, current_entry) # 新记录插入最前
            history = history[:MAX_HISTORY]  # 只保留最近10条
            save_history(name, history)
        else:
            print(f"✅ {name} 无变化")

    except Exception as e:
        print(f"❌ 任务 {name} 运行失败: {e}")