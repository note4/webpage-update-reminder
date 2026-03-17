import requests
import json
import os
import yaml
import time
import re
import feedparser

from datetime import datetime
from zoneinfo import ZoneInfo
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from collections import Counter

# ======================
# 基础配置
# ======================
HEADERS = {"User-Agent": "Mozilla/5.0"}
TIMEOUT = 10
RETRY = 3
STATE_FILE = "data.json"

# ======================
# 工具
# ======================
def load_yaml():
    with open("config.yml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {}
    return json.load(open(STATE_FILE, "r", encoding="utf-8"))

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

# ======================
# ⭐ 网络层（升级版）
# ======================
def request_with_retry(url):
    for i in range(RETRY):
        try:
            return requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"[重试{i+1}] {url} 失败: {e}")
            time.sleep(2)
    raise Exception("请求失败")

# ⭐ 自动编码识别（核心升级）
def get_html(resp):
    try:
        # 优先用 apparent_encoding
        encoding = resp.apparent_encoding

        # 特殊优化（中国站点）
        if encoding.lower() in ["gb2312", "gbk", "gb18030"]:
            encoding = "gb18030"

        return resp.content.decode(encoding, errors="ignore")

    except:
        try:
            return resp.text
        except:
            return ""

# ======================
# 时间处理
# ======================
def format_time(t):
    if not t or t == "无":
        return "无"

    try:
        dt = datetime(*time.strptime(t, "%a, %d %b %Y %H:%M:%S %z")[:6])
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        pass

    try:
        dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        pass

    return t

def extract_time(text):
    patterns = [
        r"\d{4}[-/]\d{1,2}[-/]\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日"
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return "无"

def make_key(x):
    return f"{x['title']}|{x['link']}"

# ======================
# URL模式学习
# ======================
def learn_url_patterns(links):
    paths = []
    for l in links:
        p = urlparse(l).path
        p = re.sub(r"\d+", "{num}", p)
        paths.append(p)

    counter = Counter(paths)
    return [i[0] for i in counter.most_common(3)]

def match_pattern(link, patterns):
    path = urlparse(link).path
    for p in patterns:
        r = p.replace("{num}", r"\d+")
        if re.match(r, path):
            return True
    return False

# ======================
# DOM评分（列表识别）
# ======================
def score_container(c):
    links = c.find_all("a")
    if len(links) < 5:
        return 0

    text = c.get_text(" ", strip=True)
    if not text:
        return 0

    density = len(links) / len(text)

    score = len(links) * 2 + density * 1000

    if re.search(r"\d{4}", text):
        score += 30

    if len(text) > 3000:
        score -= 20

    return score

def find_best_container(soup):
    best = None
    best_score = 0

    for c in soup.find_all(["div", "ul", "section", "article"]):
        s = score_container(c)
        if s > best_score:
            best_score = s
            best = c

    return best

# ======================
# 翻页
# ======================
def find_next_page(soup, base):
    for a in soup.find_all("a"):
        t = a.get_text()
        if any(k in t for k in ["下一页", "Next", ">", "»"]):
            href = a.get("href")
            if href:
                return urljoin(base, href)
    return None

# ======================
# HTML处理
# ======================
def handle_html(task, state, webhooks):
    name = task["name"]
    url = task["url"]

    try:
        all_data = []
        visited = set()
        cur = url

        for _ in range(3):
            if cur in visited:
                break
            visited.add(cur)

            resp = request_with_retry(cur)
            html = get_html(resp)
            soup = BeautifulSoup(html, "lxml")

            container = find_best_container(soup)
            if not container:
                break

            for a in container.find_all("a"):
                title = a.get_text(strip=True)
                if len(title) < 6:
                    continue

                href = a.get("href")
                if not href:
                    continue

                link = urljoin(cur, href)

                # 过滤垃圾链接
                if any(x in link for x in ["javascript", "#", "tag", "category"]):
                    continue

                parent = a.parent.get_text(" ", strip=True)
                t = extract_time(parent)

                all_data.append({
                    "title": title,
                    "link": link,
                    "time": format_time(t)
                })

            nxt = find_next_page(soup, cur)
            if not nxt:
                break
            cur = nxt

        patterns = learn_url_patterns([x["link"] for x in all_data])

        clean = []
        seen = set()

        for x in all_data:
            if not match_pattern(x["link"], patterns):
                continue

            k = make_key(x)
            if k not in seen:
                seen.add(k)
                clean.append(x)

        clean = clean[:30]

        if not clean:
            raise Exception("解析为空")

        process_results(name, task, clean, state, webhooks)

    except Exception as e:
        handle_fail(task, state, webhooks, str(e))

# ======================
# RSS
# ======================
def handle_rss(task, state, webhooks):
    name = task["name"]

    try:
        feed = feedparser.parse(task["url"])

        data = []
        for e in feed.entries:
            t = e.get("published") or e.get("updated") or "无"

            data.append({
                "title": e.get("title", ""),
                "link": e.get("link", ""),
                "time": format_time(t)
            })

        process_results(name, task, data, state, webhooks)

    except Exception as e:
        handle_fail(task, state, webhooks, str(e))

# ======================
# 核心
# ======================
def process_results(name, task, data, state, webhooks):
    keys = [make_key(x) for x in data]
    old = state.get(name, {}).get("keys")

    if old is None:
        push = data[:6]
    else:
        push = [x for x in data if make_key(x) not in old]

    if push:
        text = f"【{name} 有更新】\n\n"
        for i in push:
            text += f"{i['title']}\n时间：{i['time']}\n{i['link']}\n\n"

        send_feishu(webhooks[task["webhook"]], text)

    state[name] = {
        "keys": keys[:30],
        "fail": 0,
        "last_error": ""
    }

def handle_fail(task, state, webhooks, err):
    name = task["name"]

    fail = state.get(name, {}).get("fail", 0) + 1

    state[name] = {
        "keys": state.get(name, {}).get("keys", []),
        "fail": fail,
        "last_error": str(err)[:200]
    }

    if fail >= 10:
        send_feishu(webhooks[task["webhook"]],
                    f"【告警】{name} 连续失败 {fail} 次\n{err}")

# ======================
# 飞书
# ======================
def send_feishu(url, text):
    requests.post(url, json={
        "msg_type": "text",
        "content": {"text": text}
    }, timeout=10)

# ======================
# 主程序
# ======================
def main():
    cfg = load_yaml()
    tasks = cfg["tasks"]
    webhooks = cfg["webhooks"]

    state = load_state()

    for t in tasks:
        if t["type"] == "html":
            handle_html(t, state, webhooks)
        else:
            handle_rss(t, state, webhooks)

    save_state(state)

if __name__ == "__main__":
    main()