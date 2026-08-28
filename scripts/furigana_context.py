#!/usr/bin/env python3
"""Context-sensitive furigana corrections for Japanese news display.

pykakasi is a useful fallback but it is not sufficient for every contextual
reading. This module corrects high-risk patterns after generic ruby generation
without changing the visible Japanese text.
"""
import html
import re

MONTH_READINGS = {
    1:"いちがつ",2:"にがつ",3:"さんがつ",4:"しがつ",5:"ごがつ",6:"ろくがつ",
    7:"しちがつ",8:"はちがつ",9:"くがつ",10:"じゅうがつ",11:"じゅういちがつ",12:"じゅうにがつ",
}
CALENDAR_DAY_READINGS = {
    1:"ついたち",2:"ふつか",3:"みっか",4:"よっか",5:"いつか",6:"むいか",7:"なのか",8:"ようか",9:"ここのか",10:"とおか",
    11:"じゅういちにち",12:"じゅうににち",13:"じゅうさんにち",14:"じゅうよっか",15:"じゅうごにち",16:"じゅうろくにち",
    17:"じゅうしちにち",18:"じゅうはちにち",19:"じゅうくにち",20:"はつか",21:"にじゅういちにち",22:"にじゅうににち",
    23:"にじゅうさんにち",24:"にじゅうよっか",25:"にじゅうごにち",26:"にじゅうろくにち",27:"にじゅうしちにち",
    28:"にじゅうはちにち",29:"にじゅうくにち",30:"さんじゅうにち",31:"さんじゅういちにち",
}
DURATION_DAY_READINGS = {**CALENDAR_DAY_READINGS, 1:"いちにち"}
DIGIT_READINGS = {0:"れい",1:"いち",2:"に",3:"さん",4:"よん",5:"ご",6:"ろく",7:"なな",8:"はち",9:"きゅう"}
MINUTE_ENDINGS = {1:"いっぷん",2:"にふん",3:"さんぷん",4:"よんぷん",5:"ごふん",6:"ろっぷん",7:"ななふん",8:"はっぷん",9:"きゅうふん"}
PERSON_SPECIAL = {1:"ひとり",2:"ふたり",4:"よにん",7:"ななにん"}
HOUR_SPECIAL = {0:"れいじ",4:"よじ",7:"しちじ",9:"くじ"}
MONTH_DURATION_ONES = {1:"いっ",2:"に",3:"さん",4:"よん",5:"ご",6:"ろっ",7:"なな",8:"はっ",9:"きゅう"}

COUNTER_SPECS = {
    "本":({1:"いっぽん",2:"にほん",3:"さんぼん",4:"よんほん",5:"ごほん",6:"ろっぽん",7:"ななほん",8:"はっぽん",9:"きゅうほん"},"じゅっぽん",{}),
    "匹":({1:"いっぴき",2:"にひき",3:"さんびき",4:"よんひき",5:"ごひき",6:"ろっぴき",7:"ななひき",8:"はっぴき",9:"きゅうひき"},"じゅっぴき",{}),
    "杯":({1:"いっぱい",2:"にはい",3:"さんばい",4:"よんはい",5:"ごはい",6:"ろっぱい",7:"ななはい",8:"はっぱい",9:"きゅうはい"},"じゅっぱい",{}),
    "階":({1:"いっかい",2:"にかい",3:"さんがい",4:"よんかい",5:"ごかい",6:"ろっかい",7:"ななかい",8:"はっかい",9:"きゅうかい"},"じゅっかい",{}),
    "回":({1:"いっかい",2:"にかい",3:"さんかい",4:"よんかい",5:"ごかい",6:"ろっかい",7:"ななかい",8:"はっかい",9:"きゅうかい"},"じゅっかい",{}),
    "冊":({1:"いっさつ",2:"にさつ",3:"さんさつ",4:"よんさつ",5:"ごさつ",6:"ろくさつ",7:"ななさつ",8:"はっさつ",9:"きゅうさつ"},"じゅっさつ",{}),
    "軒":({1:"いっけん",2:"にけん",3:"さんげん",4:"よんけん",5:"ごけん",6:"ろっけん",7:"ななけん",8:"はっけん",9:"きゅうけん"},"じゅっけん",{}),
    "件":({1:"いっけん",2:"にけん",3:"さんけん",4:"よんけん",5:"ごけん",6:"ろっけん",7:"ななけん",8:"はっけん",9:"きゅうけん"},"じゅっけん",{}),
    "個":({1:"いっこ",2:"にこ",3:"さんこ",4:"よんこ",5:"ごこ",6:"ろっこ",7:"ななこ",8:"はっこ",9:"きゅうこ"},"じゅっこ",{}),
    "社":({1:"いっしゃ",2:"にしゃ",3:"さんしゃ",4:"よんしゃ",5:"ごしゃ",6:"ろくしゃ",7:"ななしゃ",8:"はっしゃ",9:"きゅうしゃ"},"じゅっしゃ",{}),
    "発":({1:"いっぱつ",2:"にはつ",3:"さんぱつ",4:"よんぱつ",5:"ごはつ",6:"ろっぱつ",7:"ななはつ",8:"はっぱつ",9:"きゅうはつ"},"じゅっぱつ",{}),
    "歳":({1:"いっさい",2:"にさい",3:"さんさい",4:"よんさい",5:"ごさい",6:"ろくさい",7:"ななさい",8:"はっさい",9:"きゅうさい"},"じゅっさい",{20:"はたち"}),
    "節":({1:"いっせつ",2:"にせつ",3:"さんせつ",4:"よんせつ",5:"ごせつ",6:"ろくせつ",7:"ななせつ",8:"はっせつ",9:"きゅうせつ"},"じゅっせつ",{}),
    "話":({1:"いちわ",2:"にわ",3:"さんわ",4:"よんわ",5:"ごわ",6:"ろくわ",7:"ななわ",8:"はちわ",9:"きゅうわ"},"じゅうわ",{}),
}

EXACT_RUBY = {
    "日本":"<ruby>日本<rt>にほん</rt></ruby>",
    "日本語学習":"<ruby>日本語<rt>にほんご</rt></ruby><ruby>学習<rt>がくしゅう</rt></ruby>",
}

RUBY_UNIT_RE = {
    unit: re.compile(rf"(?<!\d)(\d{{1,2}})<ruby>{unit}<rt>[^<]+</rt></ruby>")
    for unit in ("月","時","分","人",*COUNTER_SPECS.keys())
}
CALENDAR_DATE_RE = re.compile(
    r"(?<!\d)(\d{1,2})<ruby>月<rt>[^<]+</rt></ruby>(\d{1,2})<ruby>日<rt>[^<]+</rt></ruby>"
)
DURATION_DAY_RE = re.compile(
    r"(?<!\d)(\d{1,2})(?:<ruby>日間<rt>[^<]+</rt></ruby>|<ruby>日<rt>[^<]+</rt></ruby><ruby>間<rt>[^<]+</rt></ruby>)"
)
MONTH_DURATION_RE = re.compile(r"(?<!\d)(\d{1,2})([カかケヶヵ])<ruby>月<rt>[^<]+</rt></ruby>")
NUMERIC_PERSON_ABOVE_RE = re.compile(r"(?<=\d)<ruby>人以上<rt>[^<]+</rt></ruby>")
NUMERIC_PERSON_SPLIT_RE = re.compile(r"(?<=\d)<ruby>人<rt>[^<]+</rt></ruby>(?=(?:<ruby>以上<rt>[^<]+</rt></ruby>|以上))")
SCORE_TAI_RE = re.compile(r"(?<=\d)<ruby>対<rt>[^<]+</rt></ruby>(?=\d)")
PREFIX_TAI_RE = re.compile(r"<ruby>対<rt>つい</rt></ruby>(?=(?:[ァ-ヶーA-Za-z]|<ruby>[\u3400-\u9fff]))")
PAST_AFTER_RE = re.compile(r"(?<=た)<ruby>後<rt>[^<]+</rt></ruby>(?=(?:の|に|で|を|、|。|が|は|$))")
YUKUE_RE = re.compile(r"<ruby>行方<rt>なめがた</rt></ruby>(?=(?:は|が|を|の|に|も|<ruby>不明))")
US_PREFIX_RE = re.compile(
    r"<ruby>米<rt>こめ</rt></ruby>(?=(?:ドル|<ruby>(?:軍|政府|企業|市場|株|大統領|当局|連邦|議会|司法|商務|財務|国防|銀行)))"
)
COUNTRY_SUFFIX_RE = re.compile(
    r"(<ruby>(?:輸入|輸出|加盟|参加|先進|途上|対象|同盟|敵|友好)<rt>[^<]+</rt></ruby>)<ruby>国<rt>くに</rt></ruby>"
)

def number_reading(n):
    n=int(n)
    if n < 10:
        return DIGIT_READINGS[n]
    if n < 20:
        return "じゅう" + (DIGIT_READINGS[n-10] if n > 10 else "")
    if n < 100:
        tens, ones = divmod(n,10)
        return DIGIT_READINGS[tens] + "じゅう" + (DIGIT_READINGS[ones] if ones else "")
    return str(n)

def minute_reading(n):
    n=int(n)
    if not (1 <= n <= 99):
        return None
    tens, ones = divmod(n,10)
    if ones == 0:
        prefix = "" if tens == 1 else DIGIT_READINGS.get(tens)
        return (prefix + "じゅっぷん") if prefix is not None else None
    prefix = "" if tens == 0 else ("じゅう" if tens == 1 else DIGIT_READINGS[tens] + "じゅう")
    return prefix + MINUTE_ENDINGS[ones]

def hour_reading(n):
    n=int(n)
    if not (0 <= n <= 24):
        return None
    if n in HOUR_SPECIAL:
        return HOUR_SPECIAL[n]
    if n >= 10 and n % 10 in (4,7,9):
        tens=n//10
        prefix="じゅう" if tens==1 else DIGIT_READINGS[tens]+"じゅう"
        return prefix + {4:"よじ",7:"しちじ",9:"くじ"}[n%10]
    return number_reading(n)+"じ"

def person_reading(n):
    n=int(n)
    if not (1 <= n <= 99):
        return None
    return PERSON_SPECIAL.get(n, number_reading(n)+"にん")

def month_duration_reading(n):
    n=int(n)
    if not (1 <= n <= 99):
        return None
    tens,ones=divmod(n,10)
    if tens==0:
        return MONTH_DURATION_ONES[ones]+"かげつ"
    if ones==0:
        prefix="" if tens==1 else DIGIT_READINGS[tens]
        return prefix+"じゅっかげつ"
    prefix="じゅう" if tens==1 else DIGIT_READINGS[tens]+"じゅう"
    return prefix+MONTH_DURATION_ONES[ones]+"かげつ"

def counter_reading(n, unit):
    n=int(n)
    ones_map, ten_form, specials = COUNTER_SPECS[unit]
    if n in specials:
        return specials[n]
    if not (1 <= n <= 99):
        return None
    tens, ones=divmod(n,10)
    if tens == 0:
        return ones_map[ones]
    if ones == 0:
        prefix="" if tens==1 else DIGIT_READINGS[tens]
        return prefix + ten_form
    prefix="じゅう" if tens==1 else DIGIT_READINGS[tens]+"じゅう"
    return prefix + ones_map[ones]

def ruby(base, reading):
    return f"<ruby>{html.escape(str(base),quote=False)}<rt>{html.escape(str(reading),quote=False)}</rt></ruby>"

def apply_contextual_readings(original, rendered):
    """Correct known context-sensitive readings while preserving base text."""
    original=str(original or "")
    rendered=str(rendered or "")
    exact=EXACT_RUBY.get(original)
    if exact is not None:
        return exact

    def date_repl(m):
        month, day = int(m.group(1)), int(m.group(2))
        mr=MONTH_READINGS.get(month); dr=CALENDAR_DAY_READINGS.get(day)
        if not mr or not dr:
            return m.group(0)
        return ruby(f"{month}月",mr)+ruby(f"{day}日",dr)
    rendered=CALENDAR_DATE_RE.sub(date_repl,rendered)

    def duration_repl(m):
        day=int(m.group(1)); dr=DURATION_DAY_READINGS.get(day)
        return ruby(f"{day}日間",dr+"かん") if dr else m.group(0)
    rendered=DURATION_DAY_RE.sub(duration_repl,rendered)

    def month_duration_repl(m):
        n=int(m.group(1)); reading=month_duration_reading(n)
        return ruby(f"{m.group(1)}{m.group(2)}月",reading) if reading else m.group(0)
    rendered=MONTH_DURATION_RE.sub(month_duration_repl,rendered)
    rendered=rendered.replace("<ruby>数<rt>かず</rt></ruby>カ<ruby>月<rt>がつ</rt></ruby>",ruby("数カ月","すうかげつ"))
    rendered=rendered.replace("<ruby>数<rt>かず</rt></ruby>か<ruby>月<rt>がつ</rt></ruby>",ruby("数か月","すうかげつ"))

    def month_repl(m):
        month=int(m.group(1)); reading=MONTH_READINGS.get(month)
        return ruby(f"{month}月",reading) if reading else m.group(0)
    rendered=RUBY_UNIT_RE["月"].sub(month_repl,rendered)

    def hour_repl(m):
        n=int(m.group(1)); reading=hour_reading(n)
        return ruby(f"{n}時",reading) if reading else m.group(0)
    rendered=RUBY_UNIT_RE["時"].sub(hour_repl,rendered)

    def minute_repl(m):
        n=int(m.group(1)); reading=minute_reading(n)
        return ruby(f"{n}分",reading) if reading else m.group(0)
    rendered=RUBY_UNIT_RE["分"].sub(minute_repl,rendered)

    def person_repl(m):
        n=int(m.group(1)); reading=person_reading(n)
        return ruby(f"{n}人",reading) if reading else m.group(0)
    rendered=RUBY_UNIT_RE["人"].sub(person_repl,rendered)
    # pykakasi can tokenize 3+ digit counters as a suffix compound such as
    # 359<ruby>人以上<rt>ひといじょう</rt></ruby>.  In numeric context 人 is
    # the productive counter にん, regardless of whether the full number itself
    # is outside the explicit 1-99 person-reading table.
    rendered=NUMERIC_PERSON_ABOVE_RE.sub("<ruby>人以上<rt>にんいじょう</rt></ruby>", rendered)
    rendered=NUMERIC_PERSON_SPLIT_RE.sub("<ruby>人<rt>にん</rt></ruby>", rendered)

    for unit in COUNTER_SPECS:
        def counter_repl(m, unit=unit):
            n=int(m.group(1)); reading=counter_reading(n,unit)
            return ruby(f"{n}{unit}",reading) if reading else m.group(0)
        rendered=RUBY_UNIT_RE[unit].sub(counter_repl,rendered)

    # 対 is たい for numeric scores/ratios and as a news prefix (対イラン, 対米, etc.).
    rendered=SCORE_TAI_RE.sub("<ruby>対<rt>たい</rt></ruby>",rendered)
    rendered=PREFIX_TAI_RE.sub("<ruby>対<rt>たい</rt></ruby>",rendered)

    # 後 varies by syntax: Vた後 is usually あと; noun/loanword + 後 and その後 are ご in news prose.
    rendered=PAST_AFTER_RE.sub("<ruby>後<rt>あと</rt></ruby>",rendered)
    rendered=rendered.replace("その<ruby>後<rt>のち</rt></ruby>","その<ruby>後<rt>ご</rt></ruby>")
    rendered=rendered.replace("</ruby><ruby>後<rt>のち</rt></ruby>","</ruby><ruby>後<rt>ご</rt></ruby>")
    rendered=re.sub(r"(?<=[ァ-ヶーA-Za-z])<ruby>後<rt>のち</rt></ruby>","<ruby>後<rt>ご</rt></ruby>",rendered)

    # Common news homographs that pykakasi may choose as a place/food/literal reading.
    rendered=YUKUE_RE.sub("<ruby>行方<rt>ゆくえ</rt></ruby>",rendered)
    rendered=US_PREFIX_RE.sub("<ruby>米<rt>べい</rt></ruby>",rendered)
    rendered=COUNTRY_SUFFIX_RE.sub(lambda m:m.group(1)+"<ruby>国<rt>こく</rt></ruby>",rendered)
    rendered=re.sub(r"<ruby>厳<rt>いかめ</rt></ruby>(?=し(?:い|く|さ|かった|ければ))","<ruby>厳<rt>きび</rt></ruby>",rendered)

    # 数 is すう when it is a productive suffix (犠牲者数, エピソード数, 件数, etc.).
    rendered=rendered.replace("</ruby><ruby>数<rt>かず</rt></ruby>","</ruby><ruby>数<rt>すう</rt></ruby>")
    rendered=re.sub(r"(?<=[ァ-ヶーA-Za-z])<ruby>数<rt>かず</rt></ruby>","<ruby>数<rt>すう</rt></ruby>",rendered)
    return rendered
