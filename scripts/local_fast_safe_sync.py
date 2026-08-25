#!/usr/bin/env python3
"""Run Daily/Live/Archive conversion with local OPUS-MT only."""
import batch_prewarm as detector
import fast_safe_sync as fast
import local_translation_runtime as runtime
import sync_and_translate as base


def main():
    base.likely_chinese_source = detector.needs_cantonese_translation
    runtime.install()
    fast.main()


if __name__ == "__main__":
    main()
