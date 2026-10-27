# 武蔵野大学Webサイトのサイトマップ取得

武蔵野大学のトップページ（https://www.musashino-u.ac.jp/）からリンクを幅優先で辿り、ページのURLと`<title>`の文字列を辞書に格納してCSVに保存します。

## ファイル

- `kadai.py`：取得とCSV保存を行うPythonコード
- `sitemap.csv`：取得したURLとタイトル（`URL,title`の2列）
- `requirements.txt`：必要なライブラリ

## 実行方法

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python kadai.py
```

CSVはUTF-8 BOM付きで保存します。日本語、カンマ、引用符を含むタイトルもCSV形式で保存します。

途中で止めるときは`Ctrl+C`を使います。同じコマンドを実行すると`.crawl-state.json`から再開します。新しく取り直す場合は次のように実行します。

```sh
python kadai.py --restart
```

アクセス間隔を延ばす場合は`python kadai.py --delay 2`のように指定できます。1秒未満には設定できません。

## 取得の仕組みと範囲

1. トップページのURLをキューに登録します。
2. **各HTTPリクエストの前に必ず`time.sleep()`で1秒以上待機**します。リダイレクト先へのアクセスや再試行でも待機します。
3. 正常取得できたHTMLからタイトルを取り出し、辞書`sitemap`に`URL: タイトル`として保存します。タイトルがないHTMLでは空文字列を保存します。
4. `a`タグと`area`タグのリンクを絶対URLに変換し、同じホストの未取得URLをキューに追加します。
5. キューが空になるまで繰り返し、辞書からCSVを保存します。

対象は`www.musashino-u.ac.jp`上の、トップページからリンクを辿って到達できるHTTP/HTTPSのHTMLページです。フラグメント（`#`以降）は除去します。クエリ（`?`以降）は別ページを表す場合があるため保持します。リダイレクトがある場合は移動後のURLを辞書のキーにします。

PDF・画像などのファイル、別ホスト（別サブドメインを含む）、ログインが必要なページは対象外です。JavaScriptだけで追加されるリンクや、どこからもリンクされていないページは取得できません。HTTPエラーがあるURLはCSVに入れず、再開用ファイルに記録します。接続エラー・HTTP 429・HTTP 5xxでは最大3回まで再試行します。

## Gitの運用

初期コミット後、`feature/musashino-sitemap`ブランチで実装・取得結果を追加し、GitHubへpushしてPull Requestから`main`へマージするGitHub Flowで作業します。Pythonの仮想環境や取得の再開用ファイルはコミット対象から除外しています。
