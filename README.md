# 日本語版デイリー・ブリーフ

`daily-brief-newspaper` を基にした日本語ニュース版です。

## 方針

- 表示する見出し、本文、要約、解説、ナビゲーション、日時ラベルは日本語に統一します。
- 元データは `kanuli/daily-brief-newspaper` の公開データを同期し、日本語へ変換してから公開します。
- 音声は Supertonic 3 の女性音声 **F3** を使用し、`lang="ja"`、落ち着いた中立的なニュース読みのテンポで生成します。
- 日本語化に失敗した記事をそのまま中国語で公開しないよう、同期処理は翻訳失敗時に停止します。
- ニュース写真は原版と同様、権利上安全な素材以外を repository に複製しません。

## 音声設定

- Engine: Supertonic 3
- Voice: F3
- Language: Japanese (`ja`)
- Quality steps: 8
- Speed: 1.00
- Chunk length: 220 characters
- Pause: 0.34 seconds

固有の実在アナウンサーを模倣するのではなく、日本のテレビニュースに一般的な「明瞭・中立・落ち着いた」読み方を狙った設定です。

## 自動更新

`.github/workflows/sync-japanese-news.yml` が原版の `latest.json` / `live.json` を取得し、日本語版データと F3 音声を更新します。
