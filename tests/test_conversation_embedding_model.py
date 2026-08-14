from src.database.models import ConversationBlock


def test_conversation_block_has_dedicated_api_embedding_column() -> None:
    column = ConversationBlock.__table__.c.api_embedding

    assert column.nullable is True
    assert column.type.dim == 1024


def test_conversation_block_has_api_hnsw_index() -> None:
    indexes = {index.name: index for index in ConversationBlock.__table__.indexes}

    index = indexes["idx_conv_api_embedding_hnsw"]
    assert [expression.name for expression in index.expressions] == ["api_embedding"]
    assert index.dialect_options["postgresql"]["using"] == "hnsw"
