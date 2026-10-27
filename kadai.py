"""武蔵野大学の同一ホストのHTMLページを巡回し、URLとtitleをCSVに保存する。"""

import argparse
import csv
import json
import time
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup

START_URL = "https://www.musashino-u.ac.jp/"
DOMAIN = urlsplit(START_URL).hostname
# HTMLではないことが明らかなファイルはダウンロードしない。
ASSET_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".ico",
    ".css", ".js", ".zip", ".mp3", ".mp4", ".wav", ".mov", ".avi",
    ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".woff", ".woff2",
}


def normalize_url(base_url, href):
    """相対URLを絶対URLにし、別ホスト・画像等・フラグメントを除く。"""
    try:
        parts = urlsplit(urljoin(base_url, href.strip()))
        if parts.scheme not in ("http", "https") or parts.hostname != DOMAIN:
            return None
        if parts.username or parts.password or parts.port not in (None, 80, 443):
            return None
        if Path(parts.path).suffix.lower() in ASSET_EXTENSIONS:
            return None
        # クエリは別ページを指すことがあるため残す。#以降だけ取り除く。
        return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path or "/", parts.query, ""))
    except ValueError:
        return None


def fetch_page(session, url, delay):
    """リダイレクトや再試行も含め、各HTTPリクエストの前に必ず待つ。"""
    redirect_urls = set()
    for _ in range(10):
        if url in redirect_urls:
            return None, "redirect loop"
        redirect_urls.add(url)
        for attempt in range(3):
            time.sleep(delay * (2 ** attempt))
            try:
                response = session.get(
                    url, timeout=(10, 30), allow_redirects=False, stream=True
                )
            except requests.RequestException as error:
                if attempt == 2:
                    return None, str(error)
                continue
            if response.status_code == 429 or 500 <= response.status_code < 600:
                status = response.status_code
                retry_after = response.headers.get("Retry-After", "")
                response.close()
                if attempt == 2:
                    return None, "HTTP {} (3 attempts)".format(status)
                if retry_after.isdigit():
                    time.sleep(int(retry_after))
                continue
            break
        if response.status_code in (301, 302, 303, 307, 308):
            next_url = normalize_url(response.url, response.headers.get("Location", ""))
            response.close()
            if not next_url:
                return None, "redirect outside target HTML scope"
            url = next_url
            continue
        if response.status_code != 200:
            status = response.status_code
            response.close()
            return None, "HTTP {}".format(status)
        return response, None
    return None, "too many redirects"


def save_csv(sitemap, output):
    """辞書のkeyをURL、valueをtitleとして2列で保存する。"""
    output = Path(output)
    temporary = output.with_name(output.name + ".tmp")
    with temporary.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["URL", "title"])
        writer.writerows(sorted(sitemap.items()))
    temporary.replace(output)


def crawl(output, state_file, delay, restart=False):
    """幅優先探索。既に取得・登録したURLには再度アクセスしない。"""
    state_path = Path(state_file)
    if state_path.exists() and not restart:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        sitemap = state["sitemap"]  # key: URL, value: <title>内の文字列
        url_list = deque(state["pending"])
        visited = set(state["visited"])
        errors = state["errors"]
    else:
        sitemap = {}
        url_list = deque([START_URL])
        visited = set()
        errors = {}
    queued = set(url_list)

    def save_progress():
        state = {
            "sitemap": sitemap,
            "pending": list(url_list),
            "visited": sorted(visited),
            "errors": errors,
        }
        temporary = state_path.with_name(state_path.name + ".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
        temporary.replace(state_path)
        save_csv(sitemap, output)

    session = requests.Session()
    session.headers["User-Agent"] = "MusashinoSitemapAssignment/1.0 (educational crawler)"
    try:
        while url_list:
            current_url = url_list.popleft()
            queued.discard(current_url)
            if current_url in visited:
                continue
            try:
                response, error = fetch_page(session, current_url, delay)
                if error:
                    errors[current_url] = error
                else:
                    with response:
                        final_url = normalize_url(response.url, response.url)
                        content_type = response.headers.get("Content-Type", "").lower()
                        if final_url and final_url not in visited and (
                            "text/html" in content_type or "application/xhtml+xml" in content_type
                        ):
                            soup = BeautifulSoup(response.content, "html.parser")
                            sitemap[final_url] = soup.title.get_text().strip() if soup.title else ""
                            base_tag = soup.find("base", href=True)
                            base_url = urljoin(final_url, base_tag["href"]) if base_tag else final_url
                            for anchor in soup.select("a[href], area[href]"):
                                link = normalize_url(base_url, anchor["href"])
                                if link and link not in visited and link not in queued:
                                    url_list.append(link)
                                    queued.add(link)
                            visited.add(final_url)
            except requests.RequestException as error:
                # 本文の読み込みがタイムアウトした場合も、他のページを続ける。
                errors[current_url] = str(error)
            except KeyboardInterrupt:
                # 処理途中のURLは未完了としてキューに戻す。
                url_list.appendleft(current_url)
                raise
            visited.add(current_url)
            if len(visited) % 25 == 0:
                save_progress()
                print("visited={}, HTML={}, pending={}, errors={}".format(
                    len(visited), len(sitemap), len(url_list), len(errors)
                ), flush=True)
    finally:
        session.close()
        save_progress()
        print("Saved {} pages to {} (pending={}, errors={})".format(
            len(sitemap), output, len(url_list), len(errors)
        ), flush=True)
    return sitemap


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="sitemap.csv", help="保存するCSVファイル")
    parser.add_argument("--state", default=".crawl-state.json", help="再開用ファイル")
    parser.add_argument("--delay", type=float, default=1.0, help="各アクセス前の待機秒数（1秒以上）")
    parser.add_argument("--restart", action="store_true", help="最初から取得し直す")
    args = parser.parse_args()
    if not 1 <= args.delay < float("inf"):
        parser.error("--delay は1秒以上の有限の値を指定してください")
    try:
        crawl(args.output, args.state, args.delay, args.restart)
    except KeyboardInterrupt:
        print("中断しました。同じコマンドで再開できます。")
        raise SystemExit(130)


if __name__ == "__main__":
    main()
