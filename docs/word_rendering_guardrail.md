# Step 9 — Word Rendering Guardrail and Design Notes

Status: **DEFERRED** — production use blocked until the design below is implemented and tested.
Last updated: 2026-05-10

---

## Why Step 9 Is Guarded

The current implementation in `citalio/rendering/word.py` (`_replace_in_paragraph`) replaces `[@key]` markers by:
1. Collecting all text from all runs in a paragraph into one string
2. Performing the substitution
3. **Removing every existing run from the paragraph**
4. Writing a single new run with the substituted text

This violates the core guardrail: **Word rendering must not destroy document structure.**

Specifically it breaks:
- Mixed formatting within a paragraph (bold/italic/underline on different words)
- Run-level font overrides (size, family, colour)
- Hyperlinks (stored as `w:hyperlink` wrapping runs)
- Comments, tracked changes, and other XML annotations attached to individual runs
- Tables and structured content relying on specific run order

The `_allow_experimental=True` flag was added to prevent accidental production use. The CLI raises `NotImplementedError` immediately for `render docx`. The MCP server does not expose Step 9.

---

## Approved Minimal-Patch Strategy (To Be Implemented)

The replacement must operate **run-by-run** without removing any existing run. The algorithm is:

### Phase A — Locate markers across runs

A `[@key]` marker may span multiple runs (Word splits runs at arbitrary boundaries based on user editing, spell-check, etc.). The approach:

1. Walk paragraph runs left to right, accumulating text with run-index offsets.
2. Build a `[(char_offset, run_index, run_char_offset)]` index.
3. Use `MARKER_RE` to find all matches in the concatenated text.
4. For each match: determine which runs overlap the match range.

### Phase B — Patch overlapping runs

For each marker match found in Phase A:

1. **Pre-run** (run whose text ends before the marker): leave untouched.
2. **First run** (run where the marker begins): truncate run text to remove the marker prefix. Keep all other run properties (bold, italic, font, etc.) on this run.
3. **Middle runs** (runs fully inside the marker): set their `.text` to `""` (empty string, not removed). Do not call `run._element.getparent().remove(run._element)`.
4. **Last run** (run where the marker ends): set `.text` to `replacement_text + remainder_of_run_text`. Preserve the run's formatting.
5. **Post-run**: leave untouched.

This preserves all run XML elements (and their attached formatting, comments, tracked changes) while replacing only the text content.

### Phase C — Idempotency guard

After replacement, run Phase A again on the same paragraph. If a `[@key]` marker is still found, the replacement failed — raise `RuntimeError` rather than silently producing bad output.

### Required test fixture

Before removing the guard, provide:
- `tests/fixtures/step9_input.docx` — a document containing `[@key]` markers in paragraphs with:
  - Mixed bold/italic text adjacent to the marker
  - A hyperlink elsewhere in the same paragraph
  - A table cell with a marker
- `tests/test_step9_minimal_patch.py` — tests that:
  - The marker is replaced by the correct inline citation string
  - All run elements still exist (count of `<w:r>` elements is >= original count)
  - Bold/italic runs in the paragraph retain their properties
  - The hyperlink XML (`<w:hyperlink>`) is still present
  - Running twice is idempotent

---

## Guard Removal Criteria

The guard (`_allow_experimental=True` requirement) may be removed when ALL of the following are true:

1. `_replace_in_paragraph` is rewritten using the Phase A–C algorithm above.
2. `tests/test_step9_minimal_patch.py` passes with the fixture described.
3. The test verifies run-element preservation (not just text output).
4. xishi@HASHI1 has reviewed and accepted the implementation.
5. `docs/SCOPE_STATUS.md` is updated to move Step 9 from Experimental to Supported.

---

## References

- `citalio/rendering/word.py` — current experimental implementation
- `citalio/cli/main.py` — `render docx` command (raises immediately)
- `docs/standalone_citation_database_plan.md` — Section 9, Step 9 requirements
- `docs/SCOPE_STATUS.md` — overall scope status
