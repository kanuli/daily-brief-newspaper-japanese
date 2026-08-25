#!/usr/bin/env python3
"""Run rolling/topic/stock conversion with local OPUS-MT only."""
import local_translation_runtime as runtime
import sync_cantonese_layers as rolling


def main():
    runtime.install()
    rolling.main()


if __name__ == "__main__":
    main()
