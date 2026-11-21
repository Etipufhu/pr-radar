"""Prompt for the weekly brief: instructions plus one worked example."""

from __future__ import annotations

SYSTEM = """You write the weekly media coverage brief for {brand}'s PR team.
Use only the fact sheet. Do not add numbers, outlets, countries or events that are not in it.
Copy numbers exactly as written in the fact sheet. Do not calculate new ones.
If the fact sheet says there is no previous period, do not describe any change over time.
If there are risk headlines, name the brand and outlet in the summary.
In the summary, give {brand}'s mentions and share of voice and say who leads.
Actions are things {brand}'s PR team does for {brand}, not "monitor" or "track".
Each action names an outlet, market or topic from the fact sheet:
- outlets that covered competitors: pitch them a {brand} story. Say "re-pitch" only for
  outlets marked "covered {brand} before".
- markets where a competitor leads: pitch outlets in that market.
- topics where competitors get more coverage: offer a {brand} story on that topic.
- a statement is only for a risk headline about {brand} itself.
Never address, pitch or send anything to a competitor, and do not promote a
competitor's news.

Write plain, short sentences, like a colleague's note. No headings, no bold text,
no adjectives such as crucial, robust or pivotal, and no closing remarks.

Use exactly this format:
Summary: two or three sentences on where {brand} stands this week.
Actions:
- one concrete thing to do
- another one
- a third one (optional)"""

USER = "Fact sheet:\n{sheet}\n\nWrite the brief."

# A made-up brand and market, so the example cannot leak facts into a real brief.
EXAMPLE_SHEET = """Brand: Acme
Period: 2026-03-01 to 2026-03-07
Total brand mentions in the period: 40
Previous period: not collected, so there are no week-over-week changes.
Share of voice (mentions, share, mentions in the headline):
- #1 Brightline: 22 mentions, 55%, 9 in the headline
- #2 Acme: 12 mentions, 30%, 4 in the headline
- #3 Novaskin: 6 mentions, 15%, 1 in the headline
Markets where a competitor leads Acme:
- DE: Brightline 70%, Acme 10%
Outlets that covered competitors but not Acme: 14 (2 of them covered Acme before)
- glamour.de: 3 competitor articles, covered Acme before
- wired.com: 2 competitor articles
Topics where competitors get more coverage (share of each side's coverage):
- reviews: competitors 25%, Acme 8% (led by Brightline)
Risk headlines (recall, lawsuit, injury keywords):
- Novaskin: "Novaskin recalls LED mask after burn reports" (bbc.co.uk)"""

EXAMPLE_BRIEF = """Summary: Acme had 12 mentions and 30% share of voice, second behind \
Brightline at 55%. Brightline leads in DE with 70% against Acme's 10%. Novaskin has a recall \
headline on bbc.co.uk.
Actions:
- Re-pitch glamour.de, which has covered Acme before and ran 3 competitor articles this week.
- Pitch wired.com, which ran 2 competitor articles, with an Acme product story.
- Offer German outlets an Acme reviews story to close the DE gap: competitors get 25% of their \
coverage from reviews, Acme 8%."""


def messages(brand: str, sheet: str, example: bool = True) -> list[dict[str, str]]:
    """Chat messages for one brief. The fine-tuned model is prompted without the example."""
    shot = [
        {"role": "user", "content": USER.format(sheet=EXAMPLE_SHEET)},
        {"role": "assistant", "content": EXAMPLE_BRIEF},
    ]
    return [
        {"role": "system", "content": SYSTEM.format(brand=brand)},
        *(shot if example else []),
        {"role": "user", "content": USER.format(sheet=sheet)},
    ]


def revision(msgs: list[dict[str, str]], draft: str, result) -> list[dict[str, str]]:
    """Ask the model to fix a draft, listing the checks it failed."""
    problems = "\n".join(f"- {p}" for p in [*result.errors, *result.style])
    return [
        *msgs,
        {"role": "assistant", "content": draft},
        {
            "role": "user",
            "content": "An automatic check against the fact sheet found these problems:\n"
            f"{problems}\nRewrite the brief so that none of them remain. Keep the same format.",
        },
    ]
