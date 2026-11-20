"""Remove the publisher footer from the copy that goes into the index (DECISIONS.md D67).

Every dpa fact check ends with the same "about our fact checks" block: programme
disclaimer, contact address, WhatsApp hint and the ``powered by dpa-newslab`` line. It is
identical across documents and roughly a fifth of their text, so the chunk store filled
with near-duplicate passages that rank in the middle of the similarity range for almost
any query — generic tails outranking specific substance.

The block is removed here, at indexing time only: the stored document keeps its full text,
so citations and the editorial view still see the publisher's own words. Applying the rule
is a re-index, not a document edit.
"""

from __future__ import annotations

# The heading that opens the block, per publishing language. The German page says "Über
# dpa-Faktenchecks", the French one "À propos des fact-checks de la dpa", the Dutch one
# "Over dpa-factchecks".
FOOTER_HEADINGS = (
    "Über dpa-Faktenchecks",
    "À propos des fact-checks de la dpa",
    "Over dpa-factchecks",
)

# A heading this early is document content, not a footer; leave the text alone.
_MIN_TAIL_SHARE = 0.4


def strip_publisher_footer(text: str) -> str:
    """Return ``text`` without a trailing publisher block, or unchanged when there is none."""
    folded = text.casefold()
    cut = 0
    for heading in FOOTER_HEADINGS:
        index = folded.rfind(heading.casefold())
        if index > cut:
            cut = index
    if cut <= 0 or cut < len(text) * _MIN_TAIL_SHARE:
        return text
    return text[:cut].rstrip() + "\n"
