import requests, json, os, yaml, time, re, feedparser
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

HEADERS = {"User-Agent": "Mozilla/5.0"}
STATE_FILE = "data.json"

# ======================
# 基础
# ======================
def load_yaml():
    return yaml.safe_load(open("config.yml", encoding="utf-8"))

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    return json.load(open(STATE_FILE, encoding="utf-8"))

def save_state(s):
    json.dump(s, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False)

# ======================
# 网络
# ======================
def fetch(url):
    for _ in range(3):
        try:
            return requests.get(url, headers=HEADERS, timeout=10)
        except:
            time.sleep(2)
    raise Exception("request fail")

def get_html(resp, force=None):
    try:
        enc = force or resp.apparent_encoding
        return resp.content.decode(enc, errors="ignore")
    except:
        return resp.text

# ======================
# 工具
# ======================
def make_key(x):
    return f"{x['title']}|{x['link']}"

# ======================
# ⭐ 自动识别解析器
# ======================
def detect_parser(task, soup):
    url = task["url"]

    # 1️⃣ URL特征
    if "hncsmtr.com" in url:
        return "changsha"

    # 2️⃣ DOM特征（长沙结构）
    if soup.select(".list_date .listday"):
        return "changsha"

    # 3️⃣ 默认
    return "default"

# ======================
# ⭐ 解析器
# ======================

# 通用解析（智能版）
def parse_default(soup, base):
    data = []

    # 找最可能是列表的区域
    blocks = soup.find_all(["ul", "div", "section"])

    best = None
    best_score = 0

    for b in blocks:
        links = b.find_all("a")
        if len(links) < 5:
            continue

        score = len(links)
        if score > best_score:
            best_score = score
            best = b

    if not best:
        best = soup

    for a in best.find_all("a"):
        title = a.get_text(strip=True)
        if len(title) < 6:
            continue

        href = a.get("href")
        if not href:
            continue

        link = urljoin(base, href)

        if any(x in link for x in ["javascript", "#", "tag"]):
            continue

        data.append({
            "title": title,
            "link": link,
            "time": "无"
        })

    return data[:30]


# ⭐ 长沙专用
def parse_changsha(soup, base):
    data = []

    for a in soup.select("a"):
        title_tag = a.select_one("h2")
        if not title_tag:
            continue

        title = title_tag.get_text(strip=True)

        href = a.get("href")
        if not href:
            continue

        link = urljoin(base, href)

        day = a.select_one(".listday")
        ym = a.select_one(".listyear")

        if day and ym:
            t = f"{ym.text.strip()}-{day.text.strip()}"
        else:
            t = "无"

        data.append({
            "title": title,
            "link": link,
            "time": t
        })

    return data

# ======================
# 分发解析
# ======================
def parse(task, soup):
    parser = task.get("parser")

    if not parser or parser == "auto":
        parser = detect_parser(task, soup)

    if parser == "changsha":
        return parse_changsha(soup, task["url"])

    return parse_default(soup, task["url"])

# ======================
# HTML
# ======================
def handle_html(task, state, webhooks):
    name = task["name"]

    resp = fetch(task["url"])
    html = get_html(resp, task.get("force_encoding"))

    soup = BeautifulSoup(html, "lxml")

    data = parse(task, soup)

    process(name, task, data, state, webhooks)

# ======================
# RSS
# ======================
def handle_rss(task, state, webhooks):
    feed = feedparser.parse(task["url"])

    data = [{
        "title": e.get("title", ""),
        "link": e.get("link", ""),
        "time": e.get("published", "无")
    } for e in feed.entries]

    process(task["name"], task, data, state, webhooks)

# ======================
# 去重 + 推送
# ======================
def process(name, task, data, state, webhooks):
    old = set(state.get(name, {}).get("keys", []))

    push = []
    for x in data:
        k = make_key(x)
        if k not in old:
            push.append(x)

    if push:
        text = f"【{name} 有更新】\n\n"
        for i in push[:10]:
            text += f"{i['title']}\n时间：{i['time']}\n{i['link']}\n\n"

        requests.post(webhooks[task["webhook"]], json={
            "msg_type": "text",
            "content": {"text": text}
        })

    # ⭐ 历史去重池（关键）
    new_keys = list(old.union(make_key(x) for x in data))[-300:]

    state[name] = {"keys": new_keys}

# ======================
# 主程序
# ======================
def main():
    cfg = load_yaml()
    state = load_state()

    for t in cfg["tasks"]:
        try:
            if t["type"] == "html":
                handle_html(t, state, cfg["webhooks"])
            else:
                handle_rss(t, state, cfg["webhooks"])
        except Exception as e:
            print("error:", t["name"], e)

    save_state(state)

if __name__ == "__main__":
    main()