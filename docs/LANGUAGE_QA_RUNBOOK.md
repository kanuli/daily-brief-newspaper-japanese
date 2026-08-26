# Language QA runbook

Run these checks for Japanese language-quality changes:

1. `python scripts/test_newsroom_quality.py`
2. `python scripts/validate_furigana_readings.py`
3. `python scripts/validate_editorial_quality.py`
4. `python scripts/validate_vocab_quality.py`
5. `python scripts/validate_publication_readiness.py`

The pull-request and Pages workflows run the relevant checks automatically.
