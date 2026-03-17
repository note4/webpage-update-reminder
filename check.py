import requests
import re
import json
import os
import yaml
import time
import xml.etree.ElementTree as ET

# ======================
# 基础配置
# ======================
HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

TIMEOUT = 10
RETRY = 3
STATE_FILE = "data.json"

# ======================
# 工具函数
# ======================
def load_yaml():
    with open("config.yml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def request_with_retry(url):
    for i in range(RETRY):
        try:
            return requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"[重试{i+1}] {url} 失败: {e}")
            time.sleep(2)
    raise Exception("请求失败")

def send_feishu(webhook, text):
    data = {
        "msg_type": "text",
        "content": {"text": text}
    }
    requests.post(webhook, json=data, timeout=10)

# ======================
# HTML 处理（强绑定解析）
# ======================
def handle_html(task, state, webhooks):
    name = task["name"]
    url = task["url"]
    conf = task["html"]

    try:
        resp = request_with_retry(url)
        html = resp.text

        container_regex = conf.get("container")
        item_regex = conf.get("item")

        if container_regex:
            match = re.search(container_regex, html, re.S)
            if not match:
                raise Exception("container 未匹配")
            html = match.group(1)

        items = re.findall(item_regex, html, re.S)

        results = []
        for item in items:
            if len(item) == 3:
                link, title, pub_time = item
            elif len(item) == 2:
                link, title = item
                pub_time = "无"
            else:
                continue

            results.append({
                "title": title.strip(),
                "link": link.strip(),
                "time": pub_time.strip() if pub_time else "无"
            })

        # 去重 key
        new_keys = [r["title"] for r in results]

        old_keys = state.get(name, {}).get("keys", [])

        diff = [r for r in results if r["title"] not in old_keys]

        if diff:
            text = f"【{name} 有更新】\n\n"
            for d in diff[:5]:
                text += f"{d['title']}\n时间：{d['time']}\n{d['link']}\n\n"

            webhook = webhooks[task["webhook"]]
            send_feishu(webhook, text)

        # 更新状态
        state[name] = {
            "keys": new_keys[:20],
            "fail": 0
        }

    except Exception as e:
        print(f"[HTML失败] {name}: {e}")
        handle_fail(task, state, webhooks, str(e))

# ======================
# RSS 处理
# ======================
def handle_rss(task, state, webhooks):
    name = task["name"]
    url = task["url"]

    try:
        resp = request_with_retry(url)
        root = ET.fromstring(resp.content)

        items = root.findall(".//item")

        results = []
        for item in items:
            title = item.find("title")
            link = item.find("link")

            pub = (
                item.find("pubDate") or
                item.find("{http://purl.org/dc/elements/1.1/}date") or
                item.find("updated")
            )

            results.append({
                "title": title.text.strip() if title is not None else "",
                "link": link.text.strip() if link is not None else "",
                "time": pub.text.strip() if pub is not None else "无"
            })

        new_keys = [r["title"] for r in results]
        old_keys = state.get(name, {}).get("keys", [])

        diff = [r for r in results if r["title"] not in old_keys]

        if diff:
            text = f"【{name} 有更新】\n\n"
            for d in diff[:5]:
                text += f"{d['title']}\n时间：{d['time']}\n{d['link']}\n\n"

            webhook = webhooks[task["webhook"]]
            send_feishu(webhook, text)

        state[name] = {
            "keys": new_keys[:20],
            "fail": 0
        }

    except Exception as e:
        print(f"[RSS失败] {name}: {e}")
        handle_fail(task, state, webhooks, str(e))

# ======================
# 失败处理（连续10次报警）
# ======================
def handle_fail(task, state, webhooks, err):
    name = task["name"]

    fail_count = state.get(name, {}).get("fail", 0) + 1

    state[name] = {
        "keys": state.get(name, {}).get("keys", []),
        "fail": fail_count
    }

    if fail_count >= 10:
        webhook = webhooks[task["webhook"]]
        send_feishu(webhook, f"【告警】{name} 连续失败 {fail_count} 次\n错误：{err}")

# ======================
# 主函数
# ======================
def main():
    config = load_yaml()
    tasks = config["tasks"]
    webhooks = config["webhooks"]

    state = load_state()

    for task in tasks:
        if task["type"] == "html":
            handle_html(task, state, webhooks)
        elif task["type"] == "rss":
            handle_rss(task, state, webhooks)

    save_state(state)


if __name__ == "__main__":
    main()