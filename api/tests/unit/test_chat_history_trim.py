"""History trimming and the prompt-cache breakpoint in build_composition_messages.

The cap itself is easy; the property worth testing is that the *retained prefix
stays byte-identical across consecutive turns*, because that is the only reason
the trimming is block-quantised rather than a plain slice. A sliding window
passes every cap assertion you can write and still never hits the cache.
"""

from peritus.chat.agent import _trim_start, build_composition_messages
from peritus.core.config import settings


def _history(n: int) -> list[dict]:
    """n messages alternating user/assistant, each identifiable by index."""
    return [
        {"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}
        for i in range(n)
    ]


def _prefix_texts(messages: list) -> list[str]:
    """The content of every message before the final (grounded question) one."""
    out = []
    for m in messages[:-1]:
        content = m["content"]
        out.append(content if isinstance(content, str) else content[0]["text"])
    return out


def test_short_history_is_kept_whole():
    assert _trim_start(0) == 0
    assert _trim_start(settings.CHAT_HISTORY_MAX_MESSAGES) == 0


def test_trim_start_is_a_whole_number_of_blocks():
    block = settings.CHAT_HISTORY_TRIM_BLOCK
    for n in range(settings.CHAT_HISTORY_MAX_MESSAGES + 1, 200):
        start = _trim_start(n)
        assert start % block == 0, f"history of {n} trimmed to non-block offset {start}"


def test_trim_never_exceeds_the_cap():
    cap = settings.CHAT_HISTORY_MAX_MESSAGES
    for n in range(cap + 1, 200):
        assert n - _trim_start(n) <= cap, f"history of {n} kept more than {cap}"


def test_retained_prefix_is_stable_across_consecutive_turns():
    """The cache property: over a long conversation the window's start must hold
    still for several turns, not advance on every one."""
    cap = settings.CHAT_HISTORY_MAX_MESSAGES
    # Two messages per turn, well past the cap.
    starts = [_trim_start(n) for n in range(cap + 2, cap + 40, 2)]
    changes = sum(1 for a, b in zip(starts, starts[1:], strict=False) if a != b)
    turns = len(starts) - 1
    assert changes < turns, (
        f"window start moved on {changes}/{turns} turns — a sliding window never "
        "reuses a cached prefix"
    )


def test_consecutive_turns_share_a_byte_identical_prefix():
    """Concretely: for a run of turns, turn N's history prefix is a prefix of
    turn N+1's, so the cached block from N is reusable at N+1."""
    cap = settings.CHAT_HISTORY_MAX_MESSAGES
    shared = 0
    for n in range(cap + 2, cap + 20, 2):
        earlier = _prefix_texts(build_composition_messages(_history(n), "q", "ctx"))
        later = _prefix_texts(build_composition_messages(_history(n + 2), "q", "ctx"))
        if later[: len(earlier)] == earlier:
            shared += 1
    assert shared > 0, "no consecutive turn pair shared a reusable prefix"


def test_history_always_starts_with_a_user_turn():
    """Claude rejects a leading assistant message; block trimming can land on one."""
    for n in range(1, 60):
        messages = build_composition_messages(_history(n), "q", "ctx")
        assert messages[0]["role"] == "user"


def test_cache_breakpoint_sits_on_the_last_history_message():
    messages = build_composition_messages(_history(4), "q", "ctx")
    last_history = messages[-2]
    assert isinstance(last_history["content"], list)
    assert last_history["content"][0]["cache_control"] == {"type": "ephemeral"}


def test_no_history_produces_only_the_grounded_question():
    messages = build_composition_messages([], "q", "ctx")
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
