# Editorial Quality v4

This repository treats Japanese learner-facing news as publishable only when factual integrity, Japanese readability, furigana integrity, and delivery integrity are independently checked.

## Furigana

- Primary lexical engine: SudachiPy Mode C + SudachiDict-core 20260723.
- pykakasi is fallback only.
- Removing `<ruby>/<rt>` markup must reproduce source Japanese exactly.
- Golden readings are editorial specifications; corpus validation must not compare the generator against itself.
- Protected examples include 麻しん/麻疹, 氷河湖, 土砂崩れ, 山火事 and context-sensitive counters/dates.

## Translation and newsroom Japanese

- Structural Japanese plausibility alone is insufficient.
- Source/target semantic anchors protect causal agency, directional movement, named entities, numeric anchors and human-vs-household units.
- Known literal machine-translation patterns are rejected before caching and retried through validated fallback translation.
- Meaning-preserving deterministic post-edits normalize established finance/disaster newsroom terminology.
- Current Daily/Live copy is re-rendered after repair so furigana never preserves pre-repair text.

## Publication

- Editorial/content/furigana/vocabulary failures are fail-closed.
- Pending asynchronous F3 audio does not block safe news publication.
- Discord announces changed news only after GitHub Pages serves the approved JSON.
- Scheduled no-change cycles may send the Japanese-site heartbeat; original news URLs are never included in Discord.
