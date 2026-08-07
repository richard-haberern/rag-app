from dataclasses import dataclass, replace


@dataclass(frozen=True, slots=True)
class Span:
    doc_name: str
    char_start: int
    char_end: int

    def __post_init__(self) -> None:
        if self.char_start >= self.char_end:
            raise ValueError("Start of the interval has to be < end of the interval")

    @property
    def length(self) -> int:
        return self.char_end - self.char_start


def merge(spans: list[Span]) -> list[Span]:
    if not spans:
        return []
    sorted_spans = sorted(spans, key=lambda span: (span.doc_name, span.char_start))

    ret, curr = [], sorted_spans[0]
    for s in sorted_spans[1:]:
        if s.doc_name != curr.doc_name or s.char_start > curr.char_end:
            ret.append(curr)
            curr = s
        else:
            curr = replace(curr, char_end=max(curr.char_end, s.char_end))

    ret.append(curr)
    return ret


def intersect_len(span_a: Span, span_b: Span) -> int:
    if span_a.doc_name != span_b.doc_name:
        raise ValueError("Can't compare spans from different documents.")
    if span_a.char_start > span_b.char_start:
        span_a, span_b = span_b, span_a
    if span_b.char_start >= span_a.char_end:
        return 0
    if span_a.char_end > span_b.char_end:
        return (span_a.char_end - span_b.char_start) - (
            span_a.char_end - span_b.char_end
        )
    return span_a.char_end - span_b.char_start


def covered_len(gold_span: Span, retrieved: list[Span]) -> int:
    merged_spans = merge([s for s in retrieved if s.doc_name == gold_span.doc_name])
    ret = 0
    for s in merged_spans:
        ret += intersect_len(s, gold_span)
    return ret


def is_relevant(chunk_span: Span, gold_spans: list[Span], tau: float = 0.5) -> bool:
    for gs in gold_spans:
        if covered_len(gs, [chunk_span]) / (gs.char_end - gs.char_start) >= tau:
            return True
    return False


def recall(gold_spans: list[Span], spans: list[Span], tau: float) -> float:
    cnt = 0
    for gold_span in gold_spans:
        if (
            covered_len(gold_span, spans) / (gold_span.char_end - gold_span.char_start)
            >= tau
        ):
            cnt += 1
    return cnt / len(gold_spans)


def precision(gold_spans: list[Span], spans: list[Span]) -> float:
    cnt = 0
    for s in spans:
        if is_relevant(s, gold_spans):
            cnt += 1
    if len(spans) == 0:
        return 0.0
    return cnt / len(spans)


def reciprocal_rank(gold_spans: list[Span], spans: list[Span]) -> float:
    for rank, span in enumerate(spans):
        if is_relevant(span, gold_spans):
            return 1 / (rank + 1)
    return 0.0
