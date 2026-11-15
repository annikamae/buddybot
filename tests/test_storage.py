import sqlite3

import pytest

from buddy_storage import ConversationStore


def test_conversation_messages_survive_store_recreation(tmp_path):
    database = tmp_path / "buddy.sqlite3"
    store = ConversationStore(database)
    conversation_id = store.create_conversation("llama3.2:latest", "llava:latest")
    image = {"name": "diagram.png", "mime": "image/jpeg", "data": "YWJj"}

    store.add_message(
        conversation_id,
        "user",
        "Review this diagram",
        "📎 diagram.png",
        [image],
    )
    store.add_message(conversation_id, "assistant", "Looks good.", "Looks good.")

    reopened = ConversationStore(database)
    conversation = reopened.get_conversation(conversation_id)
    assert conversation is not None
    assert conversation["model"] == "llama3.2:latest"
    messages = reopened.list_messages(conversation_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["content"] == "Review this diagram"
    assert messages[0]["display"] == "📎 diagram.png"
    assert messages[0]["images"] == [image]
    assert messages[1]["content"] == "Looks good."
    assert messages[1]["images"] == []


def test_conversation_can_be_renamed_cleared_and_deleted(tmp_path):
    store = ConversationStore(tmp_path / "buddy.sqlite3")
    conversation_id = store.create_conversation("model", "vision")
    store.add_message(conversation_id, "user", "Question", "Question")

    store.update_conversation(conversation_id, title="Security review")
    assert store.get_conversation(conversation_id)["title"] == "Security review"

    store.clear_conversation(conversation_id)
    assert store.list_messages(conversation_id) == []
    assert store.get_conversation(conversation_id)["title"] == "New conversation"

    store.delete_conversation(conversation_id)
    assert store.get_conversation(conversation_id) is None


def test_invalid_message_role_is_rejected_by_database(tmp_path):
    store = ConversationStore(tmp_path / "buddy.sqlite3")
    conversation_id = store.create_conversation("model", "vision")

    with pytest.raises(sqlite3.IntegrityError):
        store.add_message(conversation_id, "system", "prompt", "prompt")


def test_update_missing_conversation_raises(tmp_path):
    store = ConversationStore(tmp_path / "buddy.sqlite3")
    with pytest.raises(KeyError):
        store.update_conversation("missing", title="Not here")
