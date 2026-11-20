"""Checks run on every generated brief before it is published.

Errors (unsupported numbers, unknown outlets, claimed trends without a baseline,
a missed risk headline, broken format) block publication. Style issues (stock
phrases that make text read as machine-written) are reported and used to pick
between candidates.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

NUMBER = re.compile(r"(?<![\w.])[+-]?\d+(?:[.,]\d+)?")
DOMAIN = re.compile(r"\b[a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)*\.(?:[a-z]{2,6})\b", re.I)
TREND = re.compile(
    r"\b(?:rose|risen|fell|fallen|grew|grown|dropped|declined|increased|decreased|"
    r"up from|down from|compared to last week|than last week|week-over-week)\b",
    re.I,
)
RISK_WORDS = re.compile(r"\b(?:risk|recall|lawsuit|sued|injur\w*|safety|complaint)", re.I)
STOCK_PHRASES = [
    "delve",
    "landscape",
    "tapestry",
    "testament",
    "pivotal",
    "crucial",
    "robust",
    "seamless",
    "leverage",
    "elevate",
    "showcase",
    "underscore",
    "navigate",
    "game-changer",
    "it's worth noting",
    "it is worth noting",
    "in conclusion",
    "overall,",
    "in today's",
    "not just",
    "not only",
    "stands out",
    "key takeaway",
    "dive into",
]
ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth"]
PROMOTE = re.compile(r"^\s*[-*]\s*(?:pitch|re-?pitch|offer|promote|share)\b", re.I)
STRENGTH = re.compile(r"\b(?:strong|lead|leads|leading|dominat\w*|ahead)\b", re.I)
PASSIVE_ACTION = re.compile(
    r"^\s*[-*]\s*(?:monitor|track|follow|watch|keep an eye|stay)", re.I | re.M
)
TOPIC_NAMES = [
    "launch",
    "deals pricing",
    "reviews",
    "gift guides",
    "skin science",
    "sustainability",
    "business",
    "awards",
]
# Country codes of the market editions and the words a brief would use for them.
COUNTRY_WORDS = {
    "US": r"\b(?:US|U\.S\.|USA|American|United States)\b",
    "GB": r"\b(?:GB|UK|U\.K\.|British|United Kingdom)\b",
    "AU": r"\b(?:AU|Australian?)\b",
    "DE": r"\b(?:DE|German|Germany)\b",
    "FR": r"\b(?:FR|French|France)\b",
    "ES": r"\b(?:ES|Spanish|Spain)\b",
    "IT": r"\b(?:Italian|Italy)\b",
    "PL": r"\b(?:PL|Polish|Poland)\b",
    "TR": r"\b(?:TR|Turkish|Turkey|Türkiye)\b",
    "SE": r"\b(?:SE|Swedish|Sweden)\b",
    "JP": r"\b(?:JP|Japanese|Japan)\b",
    "BR": r"\b(?:BR|Brazilian|Brazil)\b",
}
EXAMPLE_NAMES = ["Acme", "Brightline", "Novaskin", "glamour.de", "wired.com", "review units"]
MAX_WORDS = 170


@dataclass
class CheckResult:
    errors: list[str] = field(default_factory=list)
    style: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def score(self) -> int:
        """Lower is better; used to rank candidate briefs."""
        return 10 * len(self.errors) + len(self.style)


def _norm(num: str) -> str:
    num = num.lstrip("+-").replace(",", ".")
    if "." in num:
        num = num.rstrip("0").rstrip(".")
    return num


def allowed_numbers(sheet: str) -> set[str]:
    return {_norm(n) for n in NUMBER.findall(sheet)}


def check_brief(text: str, sheet: str, facts: dict) -> CheckResult:
    res = CheckResult()
    allowed = allowed_numbers(sheet)
    for n in NUMBER.findall(text):
        if _norm(n) not in allowed:
            res.errors.append(f"number not in the data: {n}")

    domains_in_sheet = {d.lower() for d in DOMAIN.findall(sheet)}
    for d in DOMAIN.findall(text):
        if d.lower() not in domains_in_sheet and not d[0].isdigit():
            res.errors.append(f"outlet not in the data: {d}")

    if not facts.get("baseline") and TREND.search(text):
        res.errors.append(f"claims a change without a previous period: '{TREND.search(text)[0]}'")

    if facts.get("risks") and not RISK_WORDS.search(text):
        res.errors.append("does not mention the risk headline")

    if not re.search(r"^Summary:", text, re.M) or not re.search(r"^Actions:", text, re.M):
        res.errors.append("missing 'Summary:' or 'Actions:' section")
    bullets = re.findall(r"^\s*[-*] ", text, re.M)
    if not 2 <= len(bullets) <= 4:
        res.errors.append(f"expected 2-4 action bullets, got {len(bullets)}")
    summary = text.split("Actions:", 1)[0]
    primary = facts.get("primary", "")
    row = next((b for b in facts.get("brands", []) if b.get("primary")), None)
    if row and f"{row['share_pct']}%" not in summary:
        res.errors.append(f"summary does not give {primary}'s share of voice ({row['share_pct']}%)")

    # A topic where competitors lead must not be described as a strength.
    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        for t in facts.get("topic_gaps", []):
            if (
                t["topic"] in sentence.lower()
                and STRENGTH.search(sentence)
                and (
                    primary.lower() in sentence.lower()
                    and t["leader"].lower() not in sentence.lower()
                )
            ):
                res.errors.append(f"topic gap described as a strength: {t['topic']}")

    targets = {o["outlet"].lower() for o in facts.get("outlet_gaps", {}).get("top", [])}
    targets |= {m["country"].lower() for m in facts.get("market_gaps", [])}
    targets |= {t["topic"].lower() for t in facts.get("topic_gaps", [])}
    actions = [a for a in text.split("Actions:", 1)[-1].splitlines() if re.match(r"\s*[-*] ", a)]
    if targets and not any(any(t in a.lower() for t in targets) for a in actions):
        res.errors.append("no action names an outlet, market or topic from the fact sheet")
    for _ in PASSIVE_ACTION.findall(text):
        res.style.append("passive action (monitor/track)")

    low_sheet = sheet.lower()
    for topic in TOPIC_NAMES:
        if re.search(rf"\b{topic}\b", text, re.I) and topic not in low_sheet:
            res.errors.append(f"topic not in the fact sheet: {topic}")
    if re.search(r"\bre-?pitch", text, re.I) and not facts.get("outlet_gaps", {}).get("warm"):
        res.errors.append("says re-pitch, but no listed outlet covered the brand before")

    # Rank words next to the brand must match its share-of-voice rank.
    if row:
        for m in re.finditer(rf"{re.escape(primary)}\b[^.\n]{{0,60}}?\b({'|'.join(ORDINALS)})\b",
                             summary, re.I):  # fmt: skip
            if ORDINALS.index(m[1].lower()) + 1 != row["rank"]:
                res.errors.append(f"wrong rank: '{m[1]}', the fact sheet says #{row['rank']}")

    # Actions are for the PR team's own brand, not for promoting a competitor's story.
    competitors = [b["brand"] for b in facts.get("brands", []) if not b.get("primary")]
    for a in actions:
        if PROMOTE.search(a):
            for c in competitors:
                if re.search(rf"\b{re.escape(c)}['’]s\b", a):
                    res.errors.append(f"action promotes a competitor's story: {c}")

    countries = {m["country"] for m in facts.get("market_gaps", [])}
    for code, words_re in COUNTRY_WORDS.items():
        if code not in countries and re.search(words_re, text):
            res.errors.append(f"country not in the fact sheet: {code}")
    for name in EXAMPLE_NAMES:
        if name.lower() in text.lower() and name.lower() not in low_sheet:
            res.errors.append(f"copied from the prompt example: {name}")

    words = len(text.split())
    if words > MAX_WORDS:
        res.style.append(f"too long: {words} words")

    low = text.lower()
    for phrase in STOCK_PHRASES:
        if phrase in low:
            res.style.append(f"stock phrase: '{phrase}'")
    if "**" in text or "#" in re.sub(r"#\d", "", text):
        res.style.append("markdown formatting")
    return res
