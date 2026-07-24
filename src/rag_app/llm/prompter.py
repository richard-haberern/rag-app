def build_prompt(query: str, chunks: list[tuple[int, str]]) -> str:
    context = "\n---\n".join(f"[[{i}]]\n{text}" for i, text in chunks)
    return (
        "Instructions:\n"
        " - Answer the question referencing ONLY the context below for facts.\n"
        " - If the context doesn't contain the answer, say you can't give a confident answer.\n"
        " - The '---' is used for dividing Context Chunks - after each '---' comes new context chunk for you to use.\n"
        " - The '[[i]]' are used for markers of indiviual chunks (sections) - if you use context from that section put it into the " 
        "answer at the beginning of the sentence you used it in. \n"
        "Example: \n"
        "[[1]] \n"
        "---\n"
        "Internal policy says no coffee machines are allowed in shared spaces.\n" 
        "Question: What does the internal policy says about coffee machines?\n"
        "Your answer: [[1]] The internal policy says that coffee machines are not allowed in shared spaces.\n"
        "Context:\n"
        f"{context}\n\n"
        "Question:\n"
        f"{query}\n\n"
        "Answer:"
    )