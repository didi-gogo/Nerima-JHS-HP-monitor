# 練馬区立中学校 情報巡回ツール

練馬区立中学校33校のホームページ更新を確認するGitHub Pagesツールです。

## 修正版の仕組み

学校の公開URLは、実際の内容を持たない固定フレームページです。実際の更新情報は `cms.nerima-tky.ed.jp` のCMSページとRSSにあります。

1. GitHub Actionsが3時間ごとに33校の公開URLを取得する
2. 各ページからCMSページとRSSのURLを検出する
3. CMS本文とRSS記事を正規化し、SHA-256ハッシュを作る
4. 結果を `data/status.json` に保存する
5. GitHub Pagesは同一オリジンのJSONだけを読み込むため、ブラウザのCORS制限を受けない
6. 各端末では、最後に「訪問」した時点のハッシュと最新ハッシュを比較する

取得時はキャッシュを使わず、毎回変わるアクセスカウンター、ページID、スクリプト、スタイル、空白差を比較から除外します。RSSの新規記事だけでなく、記事本文やCMSトップページの修正も検知対象です。旧公開URLが404となる学校は、現在のCMS URLへ自動的に切り替えます。

## 手動実行

GitHubの「Actions」から `Monitor school websites` を選び、`Run workflow` を実行します。結果は `data/status.json` に反映され、GitHub Pagesにも公開されます。

## ローカル確認

```sh
python3 -m unittest discover -s tests -v
python3 scripts/monitor.py
python3 -m http.server 8000
```

ブラウザで `http://localhost:8000/` を開きます。

## 取得エラー時

一時的な通信障害では、直前に成功したハッシュを保持しつつ「取得エラー」を表示します。すべての取得が失敗した場合はActions自体を失敗させます。
