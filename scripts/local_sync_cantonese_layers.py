#!/usr/bin/env python3
"""Run rolling/topic/stock conversion from one frozen Cantonese snapshot."""
import cantonese_snapshot as snapshot
import local_translation_runtime as runtime
import sync_cantonese_layers as rolling


def main():
    runtime.install()
    rolling.fetch_source = lambda name, optional=False: snapshot.load_json(name, optional=optional)
    rolling.main()


if __name__ == "__main__":
    main()
