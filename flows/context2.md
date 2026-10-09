# Project Context

> Facts only: what the system is, where things live, what words mean.
> No behavioural rules here; those go in the instructions files.
> Prefer links to authoritative docs over copied content. Copies go stale silently.
> Last reviewed: <TODO: date> by <TODO: name>

## 1. System overview

- **Product:** <TODO: one-paragraph description of the IAM system and its purpose>
- **Users / actors:** <TODO: e.g. operators, maintainers, admins, machine identities>
- **Integrity / security classification:** <TODO: SIL / basic integrity / IEC 62443 SL, per component if it differs. Leave TODO until confirmed by the team>
- **Out of scope for this repo:** <TODO>

## 2. Components and interfaces

| Component | Responsibility | Language | Path in repo |
|---|---|---|---|
| <TODO> | <TODO> | <TODO> | <TODO> |

| Interface | From → To | Protocol / format | Spec document |
|---|---|---|---|
| <TODO> | <TODO> | <TODO> | <TODO: link / doc ID> |

## 3. Repository map

```
<TODO: top-level tree, 1 line per directory with its purpose>
src/      <TODO>
tests/    <TODO>
docs/     <TODO>
```

## 4. Authoritative sources (order of precedence)

When sources conflict, the higher entry wins.

1. <TODO: requirements tool / spec documents, with location>
2. <TODO: interface control documents>
3. <TODO: architecture / design docs>
4. Source code (describes what the system *does*, never what it *should do*)

- **Requirement ID format:** <TODO: e.g. PREFIX-NNNN, with an example>
- **Test case ID format:** <TODO>
- **How versions/baselines are referenced:** <TODO>

## 5. Build, run, test

| Task | Command | Notes |
|---|---|---|
| Build | <TODO> | <TODO> |
| Run all tests | <TODO> | <TODO> |
| Run a single test | <TODO> | <TODO> |
| Coverage | <TODO> | <TODO> |
| Test environment / bench | <TODO> | <TODO: what is simulated vs real> |

- **Test frameworks in use:** <TODO: e.g. GoogleTest, pytest, Robot Framework>
- **CI:** <TODO: system, where results/artifacts are stored>

## 6. Glossary (team usage)

Record how *this team* uses each term. Where it differs from ISTQB, note it.

| Term | Team meaning | Differs from ISTQB? |
|---|---|---|
| Test case | <TODO> | <TODO> |
| Test scenario | <TODO> | <TODO> |
| Test procedure / script | <TODO> | <TODO> |
| Test specification | <TODO> | <TODO> |
| <TODO: domain terms> | <TODO> | <TODO> |

## 7. Known pitfalls

- <TODO: recurring integration failures, flaky tests, environment quirks>



# Repository Instructions

> Rules for every AI task in this repo. Facts about the system live in CONTEXT.md. Read it first.
> File name/location depends on the tool: <TODO: e.g. .github/copilot-instructions.md or CLAUDE.md>
> Changes to this file are tool-configuration changes: commit them with a reason and rerun the golden-set eval.

## Sources and grounding

- Treat CONTEXT.md §4 as the order of authority. Never use source code as the basis for what the system *should* do.
- Reference only documents listed in CONTEXT.md §4 or under <TODO: docs path>. If the information you need isn't there, say which document is missing. Don't fill the gap from general knowledge.
- Cite every claim about required behaviour with a requirement ID (format: CONTEXT.md §4).
- If a requirement is ambiguous, contradictory or doesn't define the outcome, write `UNSPECIFIED: <specific question>` and stop that item. Don't choose an interpretation silently.

## Test oracle rule

- Expected results come **only** from the test basis (requirements / interface specs), never from the implementation, existing test outputs, or logs.
- If you read source code (e.g. to find an API signature), don't let it influence expected results. State which files you read.

## Scope of changes

- Change only files the task names. List any other file you think needs changing, and don't edit it.
- Don't modify, delete, or weaken existing tests (looser assertions, skips, raised tolerances) unless the task explicitly says so.
- Don't add dependencies. <TODO: or: approved dependency list / process>

## Output

- Start with a list of what you produced, its requirement IDs, and every `UNSPECIFIED` item.
- Use the formats defined in the path-specific instruction files. Don't invent new formats.
- Mark all AI-produced artifacts: <TODO: header/tag format, e.g. model, version, date, prompt ref, "pending human review">

## Never

- Never put credentials, keys, certificates, or real user data in code, tests, or fixtures. Use <TODO: approved test-data source>.
- Never claim a test passed, ran, or covers a requirement unless you ran it and show the output.
- Never mark an artifact as reviewed or approved. Only a human does that.
- <TODO: team-specific prohibitions>