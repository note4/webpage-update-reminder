import requests
import hashlib
import json
import re

# ===== 配置 =====
URL_1 = "https://www.hncsmtr.com/909/932/index.htm"
WEBHOOK_1 = "https://open.feishu.cn/open-apis/bot/v2/hook/f918cda7-c0dc-4039-b7b9-5ae1ed036f50"

URL_2 = "https://www.williamlong.info/"
WEBHOOK_2 = "https://open.feishu.cn/open-apis/bot/v2/hook/9d8ce6c5-f99e-4ee8-8fdc-c112d1fbf06b"

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ===== 工具函数 =====
def push(webhook, msg):
    requests.post(webhook, json={
        "msg_type": "text",
        "content": {"text": msg}
    })

def md5(text):
    return hashlib.md5(text.encode()).hexdigest()

def load():
    try:
        with open("data.json", "r") as f:
            return json.load(f)
    except:
        return {}

def save(data):
    with open("data.json", "w") as f:
        json.dump(data, f)


# ===== 任务1：长沙地铁 =====
def check_metro(data):
    html = requests.get(URL_1, headers=HEADERS).text

    # 只取列表部分
    match = re.search(r'<ul.*?list.*?>(.*?)</ul>', html, re.S)
    list_html = match.group(1) if match else ""

    new_hash = md5(list_html)
    old_hash = data.get("metro")

    if old_hash and old_hash != new_hash:
        titles = re.findall(r'<a.*?>(.*?)</a>', list_html)
        msg = "【长沙地铁更新】\n" + "\n".join(titles[:5])
        push(WEBHOOK_1, msg)

    data["metro"] = new_hash


# ===== 任务2：月光博客 =====
def check_blog(data):
    html = requests.get(URL_2, headers=HEADERS).text

    # 提取文章标题（WordPress结构）
    titles = re.findall(r'<h2.*?>(.*?)</h2>', html)

    content = "\n".join(titles[:10])
    new_hash = md5(content)
    old_hash = data.get("blog")

    if old_hash and old_hash != new_hash:
        msg = "【月光博客更新】\n" + "\n".join(titles[:5])
        push(WEBHOOK_2, msg)

    data["blog"] = new_hash


# ===== 主流程 =====
def main():
    data = load()

    check_metro(data)
    check_blog(data)

    save(data)


if __name__ == "__main__":
    main()