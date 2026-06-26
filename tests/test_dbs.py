import pytest
from rag_app.schemas import DocumentDTO, ChunkDTO
from uuid import uuid4


async def test_doc_store_roundtrip(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    await session.commit()

    async with new_session() as s2:
        ret_doc = await doc_store.get_document(s2, doc.id)
    assert ret_doc.id == doc.id
    assert ret_doc.filename == doc.filename
    assert ret_doc.path_raw_content == doc.path_raw_content
    assert ret_doc.content_hash == doc.content_hash
    assert ret_doc.doc_metadata == doc.doc_metadata
   
async def test_doc_store_get_non_existing(doc_store, session, db_tests):
    with pytest.raises(ValueError):
        await doc_store.get_document(session, uuid4())


async def test_doc_store_remove(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    await doc_store.remove_document(session, doc.id)
    await session.commit()
    async with new_session() as s2:
        with pytest.raises(ValueError):
            await doc_store.get_document(s2, doc.id)


async def test_doc_store_exists(doc_store, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    await session.commit()
    async with new_session() as s2:
        assert await doc_store.exists(s2, doc)
        assert not await doc_store.exists(s2, DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdefgh", {"creator": "assasino", "size": 100}))


async def test_chunk_store_roundtrip_by_ids(chunk_store, doc_store, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
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
        assert 0 <= ch.position < 6

async def test_chunk_store_roundtrip_by_doc_id(chunk_store, doc_store, new_session, session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    await session.commit()
    async with new_session() as s2:
        ret_chunks = await chunk_store.get_chunks_by_document(s2, doc.id)
    for i, ch in enumerate(ret_chunks):
        assert ch.id == ch_ids[i]
        assert ch.document_id == doc.id
        assert ch.content == chunks[i].content
        assert 0 <= ch.position < 6



async def test_chunk_store_no_chunk_exception(chunk_store, session, db_tests):
    with pytest.raises(ValueError):
        await chunk_store.get_chunk(session, uuid4())


async def test_chunk_store_no_chunks_doc_id_exception(chunk_store, session, db_tests):
    with pytest.raises(ValueError):
        await chunk_store.get_chunks_by_document(session, uuid4())

async def test_vec_store_one_vector_roundtrip(vector_store, doc_store, chunk_store, fake_embedder, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    vector = fake_embedder.embed_document([chunks[0].content])[0]
    await vector_store.add_vector(session, ch_ids[0], vector)
    await session.commit()
    async with new_session() as s2:
        ret_vector = await vector_store.get_vector_values_by_chunk_id(s2, chunks[0].id)
    assert vector == pytest.approx(ret_vector)
    

async def test_vec_store_vectors_roundtrip(vector_store, doc_store, chunk_store, fake_embedder, session, new_session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    vectors = fake_embedder.embed_document([ch.content for ch in chunks])
    await vector_store.add_vectors(session, [(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    ret_vectors = []
    await session.commit()
    async with new_session() as s2:
        for i, _ in enumerate(vectors):
            ret_vectors.append(await vector_store.get_vector_values_by_chunk_id(s2, chunks[i].id))
    
    for i, vec in enumerate(ret_vectors):
        for j, embed in enumerate(vec):
            assert vectors[i][j] == pytest.approx(embed)


async def test_vec_store_wrong_dim(vector_store, doc_store, chunk_store, session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    with pytest.raises(ValueError):
        await vector_store.add_vector(session, uuid4(), [0,1,2,3])
    
async def test_vec_store_get_values_by_chunk_id_eror(vector_store, doc_store, chunk_store, fake_embedder, session, db_tests):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    vectors = fake_embedder.embed_document([ch.content for ch in chunks])
    await vector_store.add_vectors(session, [(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    with pytest.raises(ValueError):
        await vector_store.get_vector_values_by_chunk_id(session, uuid4())

async def test_vec_store_search(vector_store, doc_store, chunk_store, fake_embedder, session, new_session, db_tests, settings_session):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    vectors = []
    for i in range(5):
        embed = [0 for i in range(settings_session.embed_dim)]
        embed[i] = 1
        vectors.append(embed)

    await vector_store.add_vectors(session, [(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    await session.commit()
    query = [0 for i in range(settings_session.embed_dim)]
    query[0] = 1
    async with new_session() as s2:
        found_k = await vector_store.search(s2, query, 5)
    assert (ch_ids[0], pytest.approx(0.0)) == found_k[0]
    assert (ch_ids[1], pytest.approx(1.0)) == found_k[1]
    assert (ch_ids[2], pytest.approx(1.0)) == found_k[2]
    assert (ch_ids[3], pytest.approx(1.0)) == found_k[3]
    assert (ch_ids[4], pytest.approx(1.0)) == found_k[4]


async def test_vec_store_search_bad_k(vector_store, session, db_tests, settings_session):
    with pytest.raises(ValueError):
        await vector_store.search(session, [0 for i in range(settings_session.embed_dim)], 0)  


async def test_vec_store_search_k_bigger_than_db_records(vector_store, doc_store, chunk_store, fake_embedder, session, new_session, db_tests, settings_session):
    doc = DocumentDTO(uuid4(),"file1.txt", "/route/to/the/file", "0123456789abcdef", {"creator": "assasino", "size": 100})
    await doc_store.add_document(session, doc)
    ch_ids = [uuid4() for i in range(6)]
    chunks = [ChunkDTO(ch_ids[0], "abc", doc.id, 0), ChunkDTO(ch_ids[1], "def", doc.id, 1), ChunkDTO(ch_ids[2], "ghi", doc.id, 2), ChunkDTO(ch_ids[3], "jkl", doc.id, 3), ChunkDTO(ch_ids[4], "mno", doc.id, 4), ChunkDTO(ch_ids[5], "prs", doc.id, 5)]
    await chunk_store.add_chunks(session, chunks)
    vectors = []
    for i in range(5):
        embed = [0 for i in range(settings_session.embed_dim)]
        embed[i] = 1
        vectors.append(embed)
    await vector_store.add_vectors(session, [(ch_ids[i], vec) for i, vec in enumerate(vectors)])
    await session.commit()
    query = [0 for i in range(settings_session.embed_dim)]
    query[0] = 1
    async with new_session() as s2:
        found_k = await vector_store.search(s2, query, 10)
    
    assert (ch_ids[0], pytest.approx(0.0)) == found_k[0]
    assert (ch_ids[1], pytest.approx(1.0)) == found_k[1]
    assert (ch_ids[2], pytest.approx(1.0)) == found_k[2]
    assert (ch_ids[3], pytest.approx(1.0)) == found_k[3]
    assert (ch_ids[4], pytest.approx(1.0)) == found_k[4]