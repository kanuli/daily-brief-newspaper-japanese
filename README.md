# 日本語版デイリー・ブリーフ

`daily-brief-newspaper` を基にした日本語ニュース版です。

## 方針

- 表示する見出し、本文、要約、解説、ナビゲーション、日時ラベルは日本語に統一します。
- 元データは `kanuli/daily-brief-newspaper` の公開データを同期し、日本語へ変換してから公開します。
- 速報版は原版と同じ発行時刻に同期し、06:00、07:00、09:00〜24:00 HKT を対象とします。08:00 HKT は日刊版の発行枠です。
- 音声は Supertonic 3 の女性音声 **F3** を使用し、`lang="ja"`、日本のテレビニュースに一般的な明瞭・中立・落ち着いた読み方を狙います。
- 翻訳サービスの 4xx/5xx エラーページ、HTML エラー本文、未完了の繁体字中国語を日本語記事として保存・公開しません。
- 翻訳に失敗した場合は Google 翻訳の結果を検証し、必要に応じて無料の MyMemory 翻訳へフォールバックします。両方が品質検査を通らない場合は同期を停止します。
- F3 音声生成前、GitHub Pages 公開前、手動 QA、Auto Maintenance の各経路で同じコンテンツ完全性検査を行います。
- ニュース写真は原版と同様、権利上安全な素材以外を repository に複製しません。

## 音声設定

- Engine: Supertonic 3
- Voice: F3
- Language: Japanese (`ja`)
- Quality steps: 8
- Speed: 0.72
- Chunk length: 160 characters
- Delivery profile: `jp-tv-news-semantic-v4`
- Target speaking rate: Daily 340 chars/min、Live 360 chars/min
- Pause profile: 読点・意味区切り・文末・段落・セクションごとに可変

固有の実在アナウンサーを模倣するのではなく、日本のテレビニュースに一般的な「明瞭・中立・落ち着いた」読み方になるよう、意味区切りと速度上限を設定しています。

## 自動更新と公開保護

`.github/workflows/sync-japanese-news.yml` が原版の `latest.json` / `live.json` / `archive.json` を取得し、安全な日本語版データと F3 音声を更新します。

公開フローは次の順序です。

1. 原版データを取得
2. 翻訳結果のエラー本文・未翻訳本文を検査
3. 日本語本文とふりがなを生成
4. コンテンツ完全性を再検査
5. Supertonic 3 F3 音声を生成
6. 音声・タイミング・全13ページ・ローカル参照・JavaScriptをQA
7. すべて通過した場合のみ GitHub Pages へ公開

`assets/js/live-guard.js` は、万一すでに公開済みの速報データに翻訳サービスのエラー本文が含まれていた場合でも、その本文や対応音声を利用者へそのまま表示・再生しないための追加防御です。
