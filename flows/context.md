# Copilot instructions

## Orientation: use the project map first
The project map at the end of this file is the verified reference for this repository's
structure: modules, entry points, interfaces, data/state, config, key flows and risk candidates.

1. **Start from the map.** Before searching the codebase, use the map to locate the relevant
   module, file and symbol. Do not re-explore or re-map the repository.
2. **Go to the code only to:**
   - read the specific files/symbols the map points to for the current task;
   - verify a detail the task depends on (exact behaviour, current line numbers);
   - answer something the map marks `UNKNOWN` or `(inferred)`, or does not cover.
   Keep searches narrow: one module or symbol, not the whole repository.
3. **When code and map disagree, the code wins.** Say so explicitly
   ("Map is stale: X is now in path/symbol") so the map can be updated. Do not fix the map yourself.
4. **Staleness check.** The map header records the commit it was built from. If the task involves
   code that has clearly changed since then, say the map may be stale for that area.
5. **Do not repeat the map back.** Reference entries by module/path; don't restate them.

## General rules
- Cite `path` + symbol (add `:line` where useful) for every claim about the code.
- If something cannot be determined, say `UNKNOWN`. Never guess.
- The map and the code describe what the system *does*, not what it *should* do.
  Never use either as the source of expected test results; those come from requirements only.
- Do not modify production code unless explicitly asked.
- Never output credentials, keys, tokens or real hostnames; refer to file + key name only.

## Project map
<!-- Paste the output of /cartographer below this line. Replace it entirely on each update. -->
