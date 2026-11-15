"""The on-screen keyboard: which keys there are, where they sit, word
suggestions, and what each key does to the text.

The overlay treats every key as a clickable thing, so letters are picked with
exactly the same boxes as buttons on the desktop. The text is put together
here first and only typed into the real program when "Type it" is picked.
"""
from __future__ import annotations

# Common words, most frequent first, plus words useful for someone who
# communicates through this. Used for the three suggestion keys.
WORDS = list(dict.fromkeys("""
the to and a I you of in it is that for on with have be this not are but at
was my me so do your we can if what all just like no yes will about get know
how they there go from up out when one time want see think good now would
need she he her him them here could more make right who as an or by been had
has did were their our his its than then very too also really please thank
thanks help hello hi okay sorry love going come back today tomorrow tonight
home work food water hungry thirsty tired pain hurt cold hot bathroom doctor
nurse call feel better later soon again wait stop maybe because where why
which some any much many little long new old great happy sad thing something
nothing people friend family mom dad day night morning well still never
always only over after before off down way take give tell say said let look
find use open close turn play watch read write eat drink sleep
""".split()))
STARTERS = ["I", "Yes", "No"]

# 26 characters per page; they fill the letter places of the layout in order.
PAGES = {
    "abc": "abcdefghijklmnopqrstuvwxyz",
    "123": "1234567890-:;()$&@\"/+=#%*_",
}

# The keyboard is four blocks, one per quarter of the screen. Each block is
# 4 keys wide and 3 high with the two middle places left EMPTY: that is where
# the flickering circle sits, so it never covers a key.
#   L = next letter of the page, anything else is a special key.
BLOCKS = [
    ["sug0", "sug1", "sug2", "L",      "L", None, None, "L",          "L", "L", "L", "L"],
    ["L", "L", "L", "send",            "L", None, None, "send_enter", "L", "L", "L", "L"],
    ["L", "L", "L", "L",               "L", None, None, "L",          "space", ",", ".", "?"],
    ["L", "L", "L", "L",               "L", None, None, "back",       "!", "'", "page", "cancel"],
]


def _partial(text: str) -> str:
    """The unfinished word at the end of the text ('' if there is none)."""
    i = len(text)
    while i > 0 and (text[i - 1].isalpha() or text[i - 1] == "'"):
        i -= 1
    return text[i:]


def _sentence_start(before: str) -> bool:
    before = before.rstrip()
    return not before or before[-1] in ".?!"


def suggestions(text: str, n: int = 3) -> list[str]:
    part = _partial(text)
    start = _sentence_start(text[:len(text) - len(part)])
    if part:
        found = [w for w in WORDS if w.lower().startswith(part.lower()) and w.lower() != part.lower()]
    else:
        found = STARTERS if start else WORDS
    found = found[:n]
    return [w[:1].upper() + w[1:] for w in found] if start else found


def apply(text: str, key) -> str:
    """The text after pressing a key. key = (kind, value)."""
    kind, value = key[0], key[1]
    if kind == "char":
        if value.isalpha() and _sentence_start(text) and not _partial(text):
            value = value.upper()
        return text + value
    if kind == "word":
        return text[:len(text) - len(_partial(text))] + value + " "
    if kind == "space":
        return text + " "
    if kind == "back":
        return text[:-1]
    return text


def layout(area, text: str, page: str = "abc"):
    """Where every key sits.

    Returns (keys, holes): keys = [(rect, (kind, value, label))], holes = the
    four empty rectangles in the middle of each block, for the circles.
    kinds: char, word, space, back, page, send (value True = press Enter
    afterwards), cancel.
    """
    x, y, w, h = area
    gap = 8.0
    letters = iter(PAGES[page])
    words = suggestions(text)
    special = {
        "send": ("send", False, "Type it"),
        "send_enter": ("send", True, "Type it + Enter"),
        "space": ("space", " ", "space"),
        "back": ("back", "", "delete"),
        "page": ("page", "123" if page == "abc" else "abc", "123" if page == "abc" else "abc"),
        "cancel": ("cancel", "", "Cancel"),
    }
    keys, holes = [], []
    for q, block in enumerate(BLOCKS):
        bx, by = x + (q % 2) * w / 2.0, y + (q // 2) * h / 2.0
        cw, ch = (w / 2.0 - gap * 5) / 4.0, (h / 2.0 - gap * 4) / 3.0
        for i, name in enumerate(block):
            col, row = i % 4, i // 4
            rect = (bx + gap + col * (cw + gap), by + gap + row * (ch + gap), cw, ch)
            if name is None:
                if col == 1:                               # the two empty places together
                    holes.append((rect[0], rect[1], 2 * cw + gap, ch))
            elif name == "L":
                char = next(letters)
                keys.append((rect, ("char", char, char)))
            elif name.startswith("sug"):
                n = int(name[3:])
                if n < len(words):
                    keys.append((rect, ("word", words[n], words[n])))
            elif name in special:
                keys.append((rect, special[name]))
            else:                                          # punctuation
                keys.append((rect, ("char", name, name)))
    return keys, holes
