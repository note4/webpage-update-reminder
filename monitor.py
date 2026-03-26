import yaml
import requests
import feedparser
import hashlib
import json
import os

# 配置常量
CONFIG_FILE = 'config_monitor.yml'
DATA_DIR = '_sitedata'

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

# 加载配置文件
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

def get_old_sign(task_name):
    """读取该站点的历史记录"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    if os.path.exists(file_path):
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                return json.load(f).get('sign')
            except:
                return None
    return None

def save_new_sign(task_name, sign):
    """保存该站点的当前记录"""
    file_path = os.path.join(DATA_DIR, f"{task_name}.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump({"task": task_name, "sign": sign}, f, ensure_ascii=False, indent=2)

for task in config['tasks']:
    name = task['name']
    url = task['url']
    # 映射 Webhook 环境权限
    env_name = config['webhooks'].get(task['webhook'])
    webhook_url = os.environ.get(env_name) if env_name else None
    
    if not webhook_url:
        print(f"⚠️ 任务 [{name}] 跳过：未找到环境变量 {env_name}")
        continue

    print(f"正在检查: {name}")
    try:
        if task['type'] == 'rss':
            feed = feedparser.parse(url)
            if not feed.entries:
                continue
            latest_item = feed.entries[0]
            current_sign = latest_item.get('id', latest_item.link)
            content_brief = latest_item.title
            link = latest_item.link
        else:
            # HTML 监测
            headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
            resp = requests.get(url, timeout=30, headers=headers)
            resp.encoding = task.get('force_encoding', 'utf-8')
            current_sign = hashlib.md5(resp.text.encode('utf-8')).hexdigest()
            content_brief = "网页内容已发生变动"
            link = url

        # 获取旧的标识进行对比
        old_sign = get_old_sign(name)

        if old_sign != current_sign:
            # 如果不是第一次运行（即已有旧记录），则发送通知
            if old_sign is not None:
                print(f"🚀 {name} 有更新，发送通知")
                send_feishu(webhook_url, name, content_brief, link)
            else:
                print(f"📝 {name} 初始记录成功")
            
            # 更新本地文件
            save_new_sign(name, current_sign)
        else:
            print(f"✅ {name} 无变化")

    except Exception as e:
        print(f"❌ 任务 {name} 运行失败: {e}")