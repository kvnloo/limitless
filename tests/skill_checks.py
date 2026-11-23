"""Shared checks for the plugin's own skills (skills/<name>/SKILL.md): flat frontmatter, the tools a skill names,
clock times, dosing words and score/grade words offered as a feature. Not a test module itself."""
import re

CLOCK = [re.compile(r"(?i)\b\d{1,2}(:\d\d)? ?(am|pm)\b"), re.compile(r"\b\d{1,2}:\d\d\b")]
DOSING = ["mg", "mcg", "milligram", "milligrams", "microgram", "micrograms", "iu", "dose", "doses", "dosage",
          "dosages", "dosing", "supplement", "supplements", "supplementation", "melatonin", "caffeine amount",
          "caffeine dose", "how much caffeine", "titrate", "prescribe", "prescription"]
# words that would make a skill a scorer; allowed only inside a sentence that says never/no/not
SCORE_WORDS = ["score", "scores", "scored", "scoring", "grade", "grades", "graded", "grading", "level", "levels",
               "streak", "streaks", "xp", "ranking", "rank", "points", "percent", "rating"]
NEGATIONS = re.compile(r"(?i)\b(never|no|not|nor|without|none|nothing)\b")
TOOL = re.compile(r"limitless_[a-z_]+")


def frontmatter(src):
    """Flat ``key: value`` frontmatter between the two leading ``---`` lines (quotes stripped)."""
    lines = src.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("no frontmatter")
    end = lines.index("---", 1)
    out = {}
    for ln in lines[1:end]:
        if not ln.strip() or ln.startswith(" "):
            continue
        key, sep, val = ln.partition(":")
        if not sep:
            raise ValueError(f"bad frontmatter line {ln!r}")
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key.strip()] = val
    return out, "\n".join(lines[end + 1:])


def named_tools(src):
    """Every ``limitless_*`` tool name the text mentions."""
    return set(TOOL.findall(src))


def table_tools(body):
    """The tool names in markdown table rows."""
    return {t for ln in body.split("\n") if ln.startswith("|") for t in TOOL.findall(ln)}


def clock_hits(src):
    return [m.group(0) for pat in CLOCK for m in pat.finditer(src)]


def dosing_hits(src):
    low = src.lower()
    return [w for w in DOSING if re.search(r"\b" + re.escape(w) + r"\b", low)]


def sentences(src):
    """The text split into sentences, markdown line wraps joined (list items and table rows kept apart)."""
    out, para = [], []
    for ln in src.split("\n"):
        s = ln.strip()
        if not s or s.startswith(("- ", "|", "#")):
            if para:
                out.extend(re.split(r"(?<=[.;:!?])\s+", " ".join(para)))
                para = []
            if s:
                para = [s]
            continue
        para.append(s)
    if para:
        out.extend(re.split(r"(?<=[.;:!?])\s+", " ".join(para)))
    return [s for s in out if s]


def score_as_feature(src):
    """Sentences that use a score/grade/level/streak word without saying never/no/not: offering one as a feature."""
    hits = []
    for s in sentences(src):
        low = s.lower()
        if any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in SCORE_WORDS) and not NEGATIONS.search(s):
            hits.append(s)
    return hits


# The size cap the plugin's skills share: the tighter of the coach (120 lines) and learn (100 lines) caps.
SKILL_MAX_LINES = 100
FENCE = "```"


def _split_fences(src):
    """(lines outside fenced blocks, the fenced blocks' texts); an unclosed fence hides nothing."""
    outside, blocks, block = [], [], None
    for ln in src.split("\n"):
        if ln.strip().startswith(FENCE):
            if block is None:
                block = []
            else:
                blocks.append("\n".join(block))
                block = None
            continue
        if block is None:
            outside.append(ln)
        else:
            block.append(ln)
    if block is not None:   # unclosed: its lines count as outside
        outside.extend(block)
    return outside, blocks


def fenced(src):
    """The text of every closed fenced block, fences stripped."""
    return _split_fences(src)[1]


def digits_outside_fences(src):
    """Lines outside a closed fenced block that hold a digit."""
    return [ln for ln in _split_fences(src)[0] if any(c.isdigit() for c in ln)]
