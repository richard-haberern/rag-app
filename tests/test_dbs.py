import pytest
from rag_app.schemas import DocumentDTO, ChunkDTO
from rag_app.exceptions import DocumentNotFound, ChunkNotFound, VectorNotFound
from uuid import uuid4


async def test_doc_store_roundtrip(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    await session.commit()

    async with new_session() as s2:
        ret_doc = await doc_store.get_document(s2, doc.id)
    assert ret_doc.id == doc.id
    assert ret_doc.filename == doc.filename
    assert ret_doc.content_hash == doc.content_hash
    assert ret_doc.content == doc.content
    assert ret_doc.doc_metadata == doc.doc_metadata


async def test_doc_store_get_non_existing(doc_store, session, db_tests):
    with pytest.raises(DocumentNotFound):
        await doc_store.get_document(session, uuid4())


async def test_doc_store_remove(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    await doc_store.remove_document(session, doc.id)
    await session.commit()
    async with new_session() as s2:
        with pytest.raises(DocumentNotFound):
            await doc_store.get_document(s2, doc.id)


async def test_doc_store_exists(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    await session.commit()
    async with new_session() as s2:
        assert await doc_store.exists(s2, doc)
        assert not await doc_store.exists(
            s2,
            DocumentDTO(
                uuid4(),
                "file1.txt",
                "0123456789abcdefgh",
                "some amazing content in the file",
                {"creator": "assasino", "size": 100},
            ),
        )


async def test_chunk_store_roundtrip_by_ids(
    chunk_store, doc_store, session, new_session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    async with new_session() as s2:
        chunk = await chunk_store.get_chunk(s2, ch_ids[0])
        ret_chunks = await chunk_store.get_chunks_by_ids(s2, ch_ids)

    assert chunk.id == ch_ids[0]
    assert chunk.document_id == doc.id
    assert chunk.content == chunks[0].content
    assert chunk.position == 0

    for i, ch in enumerate(ret_chunks):
        assert ch.id == ch_ids[i]
        assert ch.document_id == doc.id
        assert ch.content == chunks[i].content
        assert ch.position == i


async def test_chunk_store_roundtrip_by_doc_id(
    chunk_store, doc_store, new_session, session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    async with new_session() as s2:
        ret_chunks = await chunk_store.get_chunks_by_document(s2, doc.id)
    for i, ch in enumerate(ret_chunks):
        assert ch.id == ch_ids[i]
        assert ch.document_id == doc.id
        assert ch.content == chunks[i].content
        assert ch.position == i


async def test_chunk_store_no_chunk_exception(chunk_store, session, db_tests):
    with pytest.raises(ChunkNotFound):
        await chunk_store.get_chunk(session, uuid4())


async def test_chunk_store_no_chunks_doc_id_exception(chunk_store, session, db_tests):
    with pytest.raises(ChunkNotFound):
        await chunk_store.get_chunks_by_document(session, uuid4())


async def test_vec_store_one_vector_roundtrip(
    vec_store, doc_store, chunk_store, fake_embedder, session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    # commit doc+chunks first: the store writes vectors on its own connection and the FK
    # (Vector.chunk_id -> chunks.id) needs them already visible there.
    await session.commit()
    vector = fake_embedder.embed_document([chunks[0].content])[0]
    await vec_store.add_vector(ch_ids[0], vector)
    ret_vector = await vec_store.get_vector_values_by_chunk_id(chunks[0].id)
    assert vector == pytest.approx(ret_vector)


async def test_vec_store_vectors_roundtrip(
    vec_store, doc_store, chunk_store, fake_embedder, session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    vectors = fake_embedder.embed_document([ch.content for ch in chunks])
    await vec_store.add_vectors([(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    ret_vectors = []
    for i, _ in enumerate(vectors):
        ret_vectors.append(await vec_store.get_vector_values_by_chunk_id(chunks[i].id))

    for i, vec in enumerate(ret_vectors):
        for j, embed in enumerate(vec):
            assert vectors[i][j] == pytest.approx(embed)


async def test_vec_store_wrong_dim(
    vec_store, doc_store, chunk_store, session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    with pytest.raises(ValueError):
        await vec_store.add_vector(uuid4(), [0, 1, 2, 3])


async def test_vec_store_get_values_by_chunk_id_eror(
    vec_store, doc_store, chunk_store, fake_embedder, session, db_tests
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    vectors = fake_embedder.embed_document([ch.content for ch in chunks])
    await vec_store.add_vectors([(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    with pytest.raises(VectorNotFound):
        await vec_store.get_vector_values_by_chunk_id(uuid4())


async def test_vec_store_search(
    vec_store,
    doc_store,
    chunk_store,
    fake_embedder,
    session,
    db_tests,
    settings_session,
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    vectors = []
    for i in range(5):
        embed = [0 for i in range(settings_session.embed_dim)]
        embed[i] = 1
        vectors.append(embed)

    await vec_store.add_vectors([(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    query = [0 for i in range(settings_session.embed_dim)]
    query[0] = 1
    # threshold=2.0 (cosine-distance max) so nothing is filtered out — these assertions are about
    # ordering/ties, not threshold filtering.
    found_k = await vec_store.search(query, 5, 2.0)
    # Only the nearest (query == ch_ids[0]) is unambiguously ordered; ch_ids[1..4] all tie at
    # cosine_distance 1.0 (orthogonal basis vectors) and search has no secondary sort key, so
    # their relative order is not guaranteed. Assert the head exactly and the tied tail as a set.
    assert found_k[0] == (ch_ids[0], pytest.approx(0.0))
    assert {ch_id for ch_id, _ in found_k[1:]} == {
        ch_ids[1],
        ch_ids[2],
        ch_ids[3],
        ch_ids[4],
    }
    assert all(dist == pytest.approx(1.0) for _, dist in found_k[1:])


async def test_vec_store_search_bad_k(vec_store, session, db_tests, settings_session):
    with pytest.raises(ValueError):
        await vec_store.search([0 for i in range(settings_session.embed_dim)], 0, 2.0)


async def test_vec_store_search_k_bigger_than_db_records(
    vec_store,
    doc_store,
    chunk_store,
    fake_embedder,
    session,
    db_tests,
    settings_session,
):
    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
        ChunkDTO(ch_ids[2], "ghi", doc.id, 2),
        ChunkDTO(ch_ids[3], "jkl", doc.id, 3),
        ChunkDTO(ch_ids[4], "mno", doc.id, 4),
        ChunkDTO(ch_ids[5], "prs", doc.id, 5),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    vectors = []
    for i in range(5):
        embed = [0 for i in range(settings_session.embed_dim)]
        embed[i] = 1
        vectors.append(embed)
    await vec_store.add_vectors([(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    query = [0 for i in range(settings_session.embed_dim)]
    query[0] = 1
    found_k = await vec_store.search(query, 10, 2.0)

    # Only 5 vectors exist, so k=10 returns 5. Same tie caveat as test_pgvec_store_search: the head
    # is deterministic, the four distance-1.0 results are not ordered among themselves.
    assert len(found_k) == 5
    assert found_k[0] == (ch_ids[0], pytest.approx(0.0))
    assert {ch_id for ch_id, _ in found_k[1:]} == {
        ch_ids[1],
        ch_ids[2],
        ch_ids[3],
        ch_ids[4],
    }
    assert all(dist == pytest.approx(1.0) for _, dist in found_k[1:])


# --- DocStore delete cascade (no model load) ---------------------


async def test_doc_store_remove_cascades_to_chunks_and_vectors(
    doc_store,
    chunk_store,
    pg_vector_store,
    fake_embedder,
    session,
    new_session,
    db_tests,
):
    # FK ON DELETE CASCADE (+ passive_deletes) means deleting the document removes its chunks, and
    # in turn their vectors, at the DB level.
    doc = DocumentDTO(
        uuid4(), "file1.txt", "hash-cascade", "some amazing content in the file", {}
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for _ in range(2)]
    chunks = [
        ChunkDTO(ch_ids[0], "abc", doc.id, 0),
        ChunkDTO(ch_ids[1], "def", doc.id, 1),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    vec = fake_embedder.embed_document([chunks[0].content])[0]
    await pg_vector_store.add_vector(ch_ids[0], vec)

    await doc_store.remove_document(session, doc.id)
    await session.commit()

    async with new_session() as s2:
        with pytest.raises(ChunkNotFound):
            await chunk_store.get_chunks_by_document(s2, doc.id)
    with pytest.raises(VectorNotFound):
        await pg_vector_store.get_vector_values_by_chunk_id(ch_ids[0])


async def test_vector_store_threshold(
    vec_store, doc_store, chunk_store, session, db_tests, settings_session
):

    doc = DocumentDTO(
        uuid4(),
        "file1.txt",
        "0123456789abcdef",
        "some amazing content in the file",
        {"creator": "assasino", "size": 100},
    )
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(5)]
    chunks = [
        ChunkDTO(
            ch_ids[0],
            "Python 3.14 introduced some new feature regarding GIL",
            doc.id,
            0,
        ),
        ChunkDTO(ch_ids[1], "The sun is shining bright", doc.id, 1),
        ChunkDTO(
            ch_ids[2],
            "Python is a good programming language and it is also interpreted",
            doc.id,
            2,
        ),
        ChunkDTO(ch_ids[3], "Water is blue and ocean has a lot of water", doc.id, 3),
        ChunkDTO(
            ch_ids[4],
            "Dogs and cats live at home except sometimes they don't.",
            doc.id,
            4,
        ),
    ]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()

    vectors = []
    for i in range(5):
        embed = [0 for i in range(settings_session.embed_dim)]
        embed[i] = 1
        vectors.append(embed)
    await vec_store.add_vectors([(ch_ids[i], vec) for i, vec in enumerate(vectors)])

    query = [0 for i in range(settings_session.embed_dim)]
    query[0] = 8
    query[1] = 9
    query[2] = 3
    query[3] = 1
    query[4] = 1
    res = await vec_store.search(query, 5, 0.6)
    for _, res_dist in res:
        assert res_dist <= 0.6
