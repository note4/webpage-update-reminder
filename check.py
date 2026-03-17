import requests
import json
import re
import yaml
import xml.etree.ElementTree as ET

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ===== 工具 =====
def push(webhook, msg):
    requests.post(webhook, json={
        "msg_type": "text",
        "content": {"text": msg}
    })

def load_json(file):
    try:
        with open(file, "r") as f:
            return json.load(f)
    except:
        return {}

def save_json(file, data):
    with open(file, "w") as f:
        json.dump(data, f, ensure_ascii=False)

def load_yaml(file):
    with open(file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# ===== HTML 统一处理 =====
def handle_html(task, state):
    html = requests.get(task["url"], headers=HEADERS).text

    container = task["html"].get("container")
    item_regex = task["html"]["item"]

    content = html
    if container:
        match = re.search(container, html, re.S)
        if not match:
            return
        content = match.group(1)

    items = re.findall(item_regex, content)

    parsed = []
    for link, title in items:
        link = requests.compat.urljoin(task["url"], link)
        title = re.sub('<.*?>', '', title).strip()
        parsed.append({"title": title, "link": link})

    old_links = set(state.get(task["name"], []))
    current_links = set([i["link"] for i in parsed])

    added = [i for i in parsed if i["link"] not in old_links]

    for item in added[:5]:
        msg = f"【{task['name']}更新】\n{item['title']}\n{item['link']}"
        push(task["webhook"], msg)

    state[task["name"]] = list(current_links)


# ===== RSS 处理 =====
def handle_rss(task, state):
    xml = requests.get(task["url"], headers=HEADERS).content
    root = ET.fromstring(xml)

    items = []
    for item in root.iter("item"):
        title = item.find("title").text
        link = item.find("link").text
        items.append({"title": title, "link": link})

    old_links = set(state.get(task["name"], []))
    current_links = set([i["link"] for i in items])

    added = [i for i in items if i["link"] not in old_links]

    for item in added[:5]:
        msg = f"【{task['name']}更新】\n{item['title']}\n{item['link']}"
        push(task["webhook"], msg)

    state[task["name"]] = list(current_links)


# ===== 主流程 =====
def main():
    config = load_yaml("config.yml")
    state = load_json("data.json")

    for task in config.get("tasks", []):
        if task["type"] == "html":
            handle_html(task, state)
        elif task["type"] == "rss":
            handle_rss(task, state)

    save_json("data.json", state)


if __name__ == "__main__":
    main()