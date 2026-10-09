---
applyTo: "<TODO: glob of test code, e.g. tests/**/*.cpp,tests/**/*.py. Check this does NOT match product code>"
---

# Test Implementation Instructions

> Applies to test **implementation** (test scripts / code) only.
> The test **case** design format (conditions, inputs, expected results) lives in <TODO: spec location / template> and is not defined here.
> Frontmatter syntax above is GitHub Copilot style. <TODO: adapt to the tool the team uses>

## Input

- Implement only from approved test cases: <TODO: where they live, what "approved" looks like>.
- One test function implements exactly one test case. Don't merge or split test cases. If one seems wrong, flag it.

## Traceability

- Each test carries its test case ID and requirement ID(s) as: <TODO: e.g. tag, decorator, comment, GoogleTest property>
- Example:
  ```
  <TODO: minimal example of a correctly tagged test in the team's framework>
  ```

## Structure

- Framework: <TODO: GoogleTest / pytest / ...>
- File naming: <TODO>
- Test naming: <TODO: e.g. <Component>_<Condition>_<ExpectedOutcome>>
- Layout inside a test: <TODO: e.g. Arrange / Act / Assert, precondition setup in fixtures>
- Fixtures / setup and teardown: <TODO: where shared fixtures live, when to create new ones>
- Test doubles: <TODO: which mocks/stubs/simulators are approved for which interfaces>
- Test data: <TODO: source, naming, no real identities>

## Assertions

- Assert the expected result from the test case exactly, including values, error codes and state.
- Every negative test asserts the *specific* failure (error code/type/message), not just "fails".
- Timing/tolerance values: <TODO: rule, e.g. only from the requirement, never tuned to make a test pass>

## Forbidden

- No sleeps for synchronisation. <TODO: approved waiting mechanism>
- No conditional logic that changes what is asserted.
- No disabled/skipped tests without <TODO: required annotation + ticket reference>.
- <TODO: team-specific>

## Done means

- [ ] Compiles / imports cleanly
- [ ] Test was run; output included
- [ ] Every test is tagged with test case ID + requirement ID
- [ ] <TODO: lint / static analysis / coverage step>