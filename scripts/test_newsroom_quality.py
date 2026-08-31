#!/usr/bin/env python3
"""Small deterministic regression suite for newsroom quality rules."""
import newsroom_quality as q


def main():
    cases = (
        ("約630戶需要撤離", "約630人が避難する必要があった", "household"),
        ("美股盤前走勢接近平盤", "米国株は前期市場で横ばいだった", "前期市場"),
        ("NVIDIA業績將於盤後公布", "NVIDIAの営業時間外の業績を待つ", "営業時間外"),
        ("山火控制率只有5%", "山火事はわずか5％を制御しました", "containment"),
        ("申根自由流動受影響", "衝撃的な神が動きの自由を根付かせる", "Schengen-god"),
        ("申根制度受壓", "EU内の神聖なシステムへの圧力", "Schengen-sacred-system"),
        ("申根區可暫時恢復邊境檢查", "ディバインルーツゾーンは一時的に国境検査を再開できる", "Schengen-divine-roots"),
        ("對抵達旅客實施邊境檢查", "旅行者に小切手を導入しました", "border-cheque"),
    )
    for source, target, label in cases:
        reason = q.hard_reason(source, target, "title")
        if not reason:
            raise SystemExit(f"NEWSROOM_TEST_FAIL missing {label}: {target}")

    polished = q.deterministic_postedit("山火控制率只有5%", "コントロール率は5％で、レッドフラッグの火災警告が続く", "body")
    if "鎮圧率" not in polished or "レッドフラッグ警報" not in polished:
        raise SystemExit(f"NEWSROOM_TEST_FAIL postedit={polished!r}")

    schengen = q.deterministic_postedit(
        "申根區恢復邊境檢查",
        "ディバインルーツゾーンで、到着者に小切手を導入しました",
        "body",
    )
    if "シェンゲン圏" not in schengen or "到着者に検査を導入" not in schengen:
        raise SystemExit(f"NEWSROOM_TEST_FAIL schengen-postedit={schengen!r}")

    if q.hard_reason("市場は上昇", "市場は上昇した", "body"):
        raise SystemExit("NEWSROOM_TEST_FAIL clean sentence rejected")
    print("NEWSROOM_QUALITY_TEST_OK")


if __name__ == "__main__":
    main()
