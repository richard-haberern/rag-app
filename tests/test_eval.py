from rag_app.eval.metrics import merge, intersect_len, covered_len, Span


def test_merge_empty():
    assert merge([]) == []


def test_merge_one():
    assert merge([Span("doc_a", 0, 100)]) == [Span("doc_a", 0, 100)]


def test_merge_normal():
    assert merge(
        [
            Span("doc_a", 0, 100),
            Span("doc_a", 90, 200),
            Span("doc_a", 200, 250),
            Span("doc_a", 300, 350),
            Span("doc_a", 330, 340),
            Span("doc_b", 320, 400),
            Span("doc_b", 280, 500),
        ]
    ) == [Span("doc_a", 0, 250), Span("doc_a", 300, 350), Span("doc_b", 280, 500)]


def test_intersect_normal():
    assert intersect_len(Span("doc_a", 0, 100), Span("doc_a", 90, 110)) == 10


def test_intersect_inside():
    assert intersect_len(Span("doc_a", 0, 100), Span("doc_a", 80, 90)) == 10


def test_intersect_reverse():
    assert intersect_len(Span("doc_a", 80, 110), Span("doc_a", 0, 100)) == 20


def test_intersect_same():
    assert intersect_len(Span("doc_a", 0, 100), Span("doc_a", 0, 100)) == 100


def test_intersect_disjoint():
    assert intersect_len(Span("doc_a", 0, 100), Span("doc_a", 110, 200)) == 0


def test_intersect_same_start_inside():
    assert intersect_len(Span("doc_a", 20, 100), Span("doc_a", 20, 110)) == 80


def test_covered_len_normal():
    assert (
        covered_len(
            Span("doc_a", 20, 200),
            [
                Span("doc_a", 0, 10),
                Span("doc_b", 90, 110),
                Span("doc_a", 50, 220),
                Span("doc_c", 0, 100),
                Span("doc_a", 0, 30),
            ],
        )
        == 160
    )


def test_covered_len_zero():
    assert (
        covered_len(
            Span("doc_a", 20, 200),
            [Span("doc_a", 220, 300), Span("doc_a", 350, 400), Span("doc_a", 200, 202)],
        )
        == 0
    )
