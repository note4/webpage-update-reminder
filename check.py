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
# 工具函数
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

def request_with_retry(url):
    for i in range(RETRY):
        try:
            return requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        except Exception as e:
            print(f"[重试{i+1}] {url} 失败: {e}")
            time.sleep(2)
    raise Exception("请求失败")

def send_feishu(webhook, text):
    requests.post(webhook, json={
        "msg_type": "text",
        "content": {"text": text}
    }, timeout=10)

# ======================
# 时间处理
# ======================
def format_time(time_str):
    if not time_str or time_str == "无":
        return "无"

    try:
        dt = datetime(*time.strptime(time_str, "%a, %d %b %Y %H:%M:%S %z")[:6])
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        pass

    try:
        dt = datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        dt = dt.astimezone(ZoneInfo("Asia/Shanghai"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        pass

    return time_str

def extract_time(text):
    patterns = [
        r"\d{4}-\d{1,2}-\d{1,2}",
        r"\d{4}/\d{1,2}/\d{1,2}",
        r"\d{4}年\d{1,2}月\d{1,2}日"
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(0)
    return "无"

def make_key(item):
    return f"{item['title']}|{item['link']}"

# ======================
# URL规则学习
# ======================
def learn_url_patterns(links):
    paths = []

    for link in links:
        path = urlparse(link).path
        if re.search(r'/\d+', path):
            paths.append(re.sub(r'\d+', '{num}', path))
        else:
            paths.append(path)

    counter = Counter(paths)
    return [p for p, _ in counter.most_common(3)]

def match_url_pattern(link, patterns):
    path = urlparse(link).path
    for p in patterns:
        regex = p.replace("{num}", r"\d+")
        if re.match(regex, path):
            return True
    return False

# ======================
# DOM评分
# ======================
def score_container(c):
    links = c.find_all("a")
    if len(links) < 5:
        return 0

    text = c.get_text(" ", strip=True)
    text_len = len(text)

    if text_len == 0:
        return 0

    density = len(links) / text_len

    score = len(links) * 2
    score += density * 1000

    if re.search(r"\d{4}[-/年]\d{1,2}", text):
        score += 30

    if text_len > 3000:
        score -= 20

    return score

def find_best_container(soup):
    candidates = soup.find_all(["div", "ul", "section", "article"])

    best = None
    best_score = 0

    for c in candidates:
        s = score_container(c)
        if s > best_score:
            best_score = s
            best = c

    return best

# ======================
# 翻页
# ======================
def find_next_page(soup, base_url):
    for a in soup.find_all("a"):
        text = a.get_text()
        if any(k in text for k in ["下一页", "Next", ">", "»"]):
            href = a.get("href")
            if href:
                return urljoin(base_url, href)
    return None

# ======================
# HTML处理
# ======================
def handle_html(task, state, webhooks):
    name = task["name"]
    url = task["url"]

    try:
        all_results = []
        visited = set()
        current_url = url

        for _ in range(3):
            if current_url in visited:
                break
            visited.add(current_url)

            resp = request_with_retry(current_url)
            soup = BeautifulSoup(resp.text, "lxml")

            container = find_best_container(soup)
            if not container:
                break

            for a in container.find_all("a"):
                title = a.get_text(strip=True)
                if not title or len(title) < 6:
                    continue

                href = a.get("href")
                if not href:
                    continue

                link = urljoin(current_url, href)
                if "javascript:" in link:
                    continue

                parent_text = a.parent.get_text(" ", strip=True)
                t = extract_time(parent_text)

                all_results.append({
                    "title": title,
                    "link": link,
                    "time": format_time(t)
                })

            next_page = find_next_page(soup, current_url)
            if not next_page:
                break

            current_url = next_page

        # URL规则过滤
        patterns = learn_url_patterns([r["link"] for r in all_results])

        filtered = [
            r for r in all_results
            if match_url_pattern(r["link"], patterns)
        ]

        # 去重
        seen = set()
        clean = []
        for r in filtered:
            k = make_key(r)
            if k not in seen:
                seen.add(k)
                clean.append(r)

        clean = clean[:30]

        if not clean:
            raise Exception("解析为空")

        process_results(name, task, clean, state, webhooks)

    except Exception as e:
        handle_fail(task, state, webhooks, str(e))

# ======================
# RSS处理
# ======================
def handle_rss(task, state, webhooks):
    name = task["name"]
    url = task["url"]

    try:
        feed = feedparser.parse(url)

        results = []
        for e in feed.entries:
            t = e.get("published") or e.get("updated") or "无"

            results.append({
                "title": e.get("title", "").strip(),
                "link": e.get("link", "").strip(),
                "time": format_time(t)
            })

        process_results(name, task, results, state, webhooks)

    except Exception as e:
        handle_fail(task, state, webhooks, str(e))

# ======================
# 核心逻辑
# ======================
def process_results(name, task, results, state, webhooks):
    keys = [make_key(r) for r in results]
    old_keys = state.get(name, {}).get("keys")

    if old_keys is None:
        push = results[:6]
    else:
        push = [r for r in results if make_key(r) not in old_keys]

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

# ======================
# 失败处理
# ======================
def handle_fail(task, state, webhooks, err):
    name = task["name"]

    fail = state.get(name, {}).get("fail", 0) + 1

    state[name] = {
        "keys": state.get(name, {}).get("keys", []),
        "fail": fail,
        "last_error": str(err)[:200]
    }

    if fail >= 10:
        send_feishu(
            webhooks[task["webhook"]],
            f"【告警】{name} 连续失败 {fail} 次\n{err}"
        )

# ======================
# 主函数
# ======================
def main():
    config = load_yaml()
    tasks = config["tasks"]
    webhooks = config["webhooks"]

    state = load_state()

    for t in tasks:
        if t["type"] == "html":
            handle_html(t, state, webhooks)
        else:
            handle_rss(t, state, webhooks)

    save_state(state)

if __name__ == "__main__":
    main()