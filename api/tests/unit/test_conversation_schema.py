"""What `GET /conversations/{id}` gives back for a cited answer.

`test_grounding.py` covers what a citation is *emitted* as; nothing covered what
it is *returned* as, and the gap cost the chat its passages: the response model
declared three fields, so Pydantic dropped the text on every reload while the
JSONB row kept it. These tests are that missing half — the stored dict, through
the model, out the other side.
"""

from datetime import UTC, datetime

from peritus.api.schemas.conversations import Citation, ConversationMessageOut
from peritus.chat.grounding import Passage, used_citations

STORED = {
    "n": 3,
    "label": "Langstroth on the Hive and the Honey-Bee",
    "source_id": 812,
    "text": "Removal reduced mite load by 43% relative to untreated controls.",
    "chunk_id": 9001,
    "disputed": True,
    "dispute_points": ["Whether mechanical control alone holds the threshold."],
}


def test_a_stored_citation_survives_the_response_model():
    out = Citation.model_validate(STORED).model_dump()
    assert out == STORED


def test_a_message_keeps_its_citations_whole():
    message = ConversationMessageOut.model_validate(
        {
            "id": 2,
            "role": "assistant",
            "content": "An answer [3].",
            "citations": [STORED],
            "has_contradiction": True,
            "interrupted": False,
            "created_at": datetime(2026, 9, 17, 9, 0, tzinfo=UTC),
        }
    )
    assert message.citations is not None
    assert message.citations[0].text == STORED["text"]
    assert message.citations[0].chunk_id == 9001
    assert message.citations[0].dispute_points == STORED["dispute_points"]


def test_an_answer_stored_before_the_fields_existed_still_reads():
    # Three keys is what the column holds for older answers; the client's
    # fallback is written for exactly this, so it must not be an error.
    old = Citation.model_validate({"n": 1, "label": "A title", "source_id": 4})
    assert old.text is None
    assert old.chunk_id is None
    assert old.disputed is False
    assert old.dispute_points == []


def test_every_field_the_stream_emits_is_a_field_the_model_keeps():
    # The docstring on `Citation` promises "the exact shape the SSE `sources`
    # event emits and JSONB stores". This is that promise, as a test.
    emitted = used_citations(
        [Passage(index=1, citation="A title", source_id=4, text="A passage.", chunk_id=11)],
        cited={1},
    )
    assert set(emitted[0]) <= set(Citation.model_fields)
    assert Citation.model_validate(emitted[0]).model_dump() == emitted[0]
