#!/usr/bin/env python3
"""Laugh Track: The Crypto Trading Joke Contest.

Writes one original one-line joke about crypto and trading life to
$MAKEFUN_OUTPUT_DIR/entry.txt (default /output/entry.txt).

The joke must be a single line of 1-200 characters of UTF-8 text.
This program validates the line before writing it, then re-reads
the file and verifies it matches byte for byte.

The joke itself is fixed: it is the competition entry, so the
program never edits, reformats, or truncates it.  Everything else
in this file exists to make sure that exact line reaches the
output file intact — validated, written, and re-read — and to
fail loudly instead of silently shipping a damaged entry.

Design
------
The program is split into small, single-purpose functions so each
step can be read (and tested) on its own:

* :func:`joke_stats` — measures the joke (characters, words).
* :func:`validate_joke` — runs every rule and collects all
  failures at once, instead of stopping at the first one.
* :func:`resolve_output_path` — works out where ``entry.txt`` goes.
* :func:`write_joke` / :func:`verify_joke` — write the file, then
  prove the bytes on disk match the joke exactly.
* :func:`main` — wires the steps together and owns the exit code.

One deliberate detail: the file is written with *no* trailing
newline, exactly as the original entry specifies — the file
contains the joke and nothing else.  The verifier checks for
that exact form.

Running it
-----------
::

    python3 main.py

With a custom output directory::

    MAKEFUN_OUTPUT_DIR=/tmp/out python3 main.py

Exit code 0 means the joke was written and verified; any other
code means nothing usable was produced and the error on stderr
says what went wrong.
"""

import hashlib
import os
import sys

# ---------------------------------------------------------------------------
# The joke (do not edit: this exact line is the competition entry)
#
# Written with explicit escapes so the two non-ASCII characters are
# unambiguous in any editor: \u2019 is the right single quote in
# "I'm", and \u2014 is the em dash before "I'm a long-term holder".
# ---------------------------------------------------------------------------

JOKE = "I bought the dip. Then the dip dipped. Now I\u2019m not a trader \u2014 I\u2019m a long-term holder with a support group."

# ---------------------------------------------------------------------------
# Limits from the competition brief
# ---------------------------------------------------------------------------

MAX_CHARS = 200
MIN_CHARS = 1
MAX_WORDS = None  # No word limit for this competition; kept for symmetry.
OUTPUT_FILENAME = "entry.txt"
DEFAULT_OUTPUT_DIR = "/output"


# ---------------------------------------------------------------------------
# Measuring the joke
# ---------------------------------------------------------------------------

def joke_stats(text):
    """Return a small dict describing ``text``.

    The counts are character counts (Python ``len``, i.e. Unicode
    code points) and whitespace-separated word counts — the same
    units the limits above are expressed in, so a comparison
    between the two can never be off by a unit mismatch.  The byte
    count is included too, because the file is verified in UTF-8
    bytes and the two non-ASCII characters take more than one
    byte each.
    """
    return {
        "chars": len(text),
        "words": len(text.split()),
        "bytes": len(text.encode("utf-8")),
        "lines": text.count("\n") + 1,
    }


def format_stats(stats):
    """Render the stats dict as one short human-readable fragment."""
    return "{chars} characters, {words} words".format(**stats)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def check_not_empty(text):
    """The joke must contain at least one character (brief: 1-200)."""
    if len(text) < MIN_CHARS or not text.strip():
        return "joke must not be empty"
    return None


def check_no_padding(text):
    """The joke must not start or end with whitespace.

    Leading or trailing spaces would survive the write and change
    what a judge reads, so they are rejected here rather than
    silently stripped — stripping would alter the entry.
    """
    if text != text.strip():
        return "joke must not be padded with whitespace"
    return None


def check_single_line(text):
    """The joke must be exactly one line: no CR or LF anywhere."""
    if "\n" in text or "\r" in text:
        return "joke must be a single line"
    return None


def check_char_limit(text):
    """The joke must be 1-200 characters, per the brief."""
    if len(text) > MAX_CHARS:
        return "joke is {n} characters, over the {limit} limit".format(
            n=len(text), limit=MAX_CHARS
        )
    return None


def check_word_limit(text):
    """The joke must fit within ``MAX_WORDS`` words, if one applies."""
    if MAX_WORDS is not None and len(text.split()) > MAX_WORDS:
        return "joke is {n} words, over the {limit} limit".format(
            n=len(text.split()), limit=MAX_WORDS
        )
    return None


def check_no_control_chars(text):
    """The joke must contain no invisible control characters.

    A stray tab or escape byte would be invisible in most editors
    but would still be part of the submitted text, so any
    character below U+0020 (other than the line breaks already
    rejected above) or the DEL character is refused.
    """
    for char in text:
        if ord(char) < 0x20 or ord(char) == 0x7F:
            return "joke contains a control character (U+{code:04X})".format(
                code=ord(char)
            )
    return None


def check_about_trading(text):
    """The joke should be about trading, per the competition theme.

    The brief asks for a joke about crypto and trading life, so
    the line is expected to mention the trade itself — buying,
    holding, or the dip.  This is a style guard, not a grading
    rule: it catches a line that was pasted in incomplete.
    """
    lowered = text.lower()
    trading_words = ("bought", "buy", "trader", "trading", "holder", "dip")
    if not any(word in lowered for word in trading_words):
        return "joke does not mention trading"
    return None


def check_ends_with_punctuation(text):
    """A one-line joke should end on a terminal punctuation mark.

    This is a style guard, not a competition rule: it catches a
    line that was accidentally cut short before it was pasted in.
    """
    if text and text[-1] not in ".!?":
        return "joke does not end with terminal punctuation"
    return None


# Every check, in the order its failure should be reported.  Adding a
# new rule is a one-line change here plus one function above.
CHECKS = (
    check_not_empty,
    check_no_padding,
    check_single_line,
    check_char_limit,
    check_word_limit,
    check_no_control_chars,
    check_about_trading,
    check_ends_with_punctuation,
)


def validate_joke(text):
    """Run every check and return the list of failures (empty = valid).

    All checks run even after one fails, so a single run reports
    everything wrong with the joke instead of making the author
    fix problems one at a time.
    """
    failures = []
    for check in CHECKS:
        problem = check(text)
        if problem is not None:
            failures.append(problem)
    return failures


# ---------------------------------------------------------------------------
# Writing and verifying the output file
# ---------------------------------------------------------------------------

def resolve_output_path():
    """Return the full path of the file to write.

    ``MAKEFUN_OUTPUT_DIR`` overrides the default; the directory is
    created if it does not exist yet, so the program works both in
    the grading sandbox and on a plain local machine.
    """
    output_dir = os.environ.get("MAKEFUN_OUTPUT_DIR", DEFAULT_OUTPUT_DIR)
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, OUTPUT_FILENAME)


def write_joke(text, path):
    """Write ``text`` to ``path`` as UTF-8, with no trailing newline.

    The file holds exactly the joke — no added newline, no added
    whitespace — because that is the entry format this competition
    specifies.  ``newline=""`` keeps Python from translating
    anything on the way out.
    """
    with open(path, "w", encoding="utf-8", newline="") as handle:
        handle.write(text)


def verify_joke(text, path):
    """Re-read ``path`` and prove it matches the joke byte for byte.

    Returns ``None`` on success, or an error string.  The check is
    done on raw bytes (and cross-checked with a SHA-256 digest) so
    that even a difference invisible to the eye — a changed byte,
    an added newline, a different encoding — is caught.
    """
    expected = text.encode("utf-8")
    with open(path, "rb") as handle:
        actual = handle.read()
    if actual != expected:
        return "written entry does not match the joke byte for byte"
    if hashlib.sha256(actual).hexdigest() != hashlib.sha256(expected).hexdigest():
        return "written entry failed its checksum"
    return None


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    """Validate, write, and verify the joke; return the exit code."""
    joke = JOKE

    failures = validate_joke(joke)
    if failures:
        for failure in failures:
            print("error: {failure}".format(failure=failure), file=sys.stderr)
        return 1

    try:
        path = resolve_output_path()
    except OSError as exc:
        print("error: cannot create output directory: {exc}".format(exc=exc),
              file=sys.stderr)
        return 1

    try:
        write_joke(joke, path)
    except OSError as exc:
        print("error: cannot write {path}: {exc}".format(path=path, exc=exc),
              file=sys.stderr)
        return 1

    problem = verify_joke(joke, path)
    if problem is not None:
        print("error: {problem}".format(problem=problem), file=sys.stderr)
        return 1

    print("Wrote {stats} to {path}:".format(
        stats=format_stats(joke_stats(joke)), path=path))
    print(joke)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
