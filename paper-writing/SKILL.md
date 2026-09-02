---
name: paper-writing
description: Conventions for writing and editing academic papers (LaTeX). Enforces captions that state the conclusion (not describe the table), a topic comment before every paragraph, units on every table column and plot axis, and consistent compact references. Use whenever creating or editing paper .tex source.
author: Matthew Guthaus
user_invocable: true
---

# Paper Writing

Conventions for the user's academic papers. Apply these to every `.tex` edit.

## Rule 1 — Captions state the conclusion, not the contents

A caption is **not** a description of what the table/figure shows, how it was
measured, or what the columns mean — that belongs in the body text. A caption
states **the single conclusion the reader should draw** from the table or figure.

- **One sentence.** If it runs past ~15–20 words or two clauses, it is too long.
- **No method, no column glossary, no data recitation.** Do not restate numbers,
  seed counts, units, or what each row is — the text and the table itself carry
  that. Put measurement caveats (n, σ, units, "in progress") in the body prose.
- **Write the takeaway, verbatim as you'd want the reader to remember it.**

Bad (describes the table, method, and data — belongs in text):
> Per-design PPA improvement (%) over the default move sequence, for each
> decomposition. Every design improves 14–19%, and each decomposition wins at
> least one design. Values are the known-σ race; a per-config-σ re-confirmation
> reproduced every winning arm within 0.7 points...

Good (states the conclusion):
> Per-design move-order tuning pays 14–19%, and no single decomposition wins
> everywhere.

More examples of the form:
- "Seed noise is largest exactly where tuning matters most."
- "A single global σ cannot model the noise."
- "The best recipe is a design-specific equivalence class, not a transferable sequence."

If a genuinely necessary qualifier can't fit (rare), it goes in the body sentence
that first references the table (`Table~\ref{...} shows ...`), never the caption.

## Rule 2 — Every paragraph gets a topic comment

Immediately before **every** paragraph (and section/subsection), put a LaTeX
comment naming that paragraph's single topic. This is the paper's living outline:
it keeps each paragraph focused on one idea and lets the whole argument be read by
grepping the comments.

Format: `% >> <LOCATOR>: <topic / claim of this paragraph>`

- `<LOCATOR>` = section/paragraph tag, e.g. `II.C.p2`, `IV.A`, `V.A.p3` — so the
  outline reads in order.
- `<topic>` = the one thing this paragraph argues. If you cannot write it in a few
  words, the paragraph is doing too much — split it.
- Include `[tab:x]` / `[fig:y]` in the comment when the paragraph anchors a float.

Example:
```latex
% >> II.C.p2 FINDING: effCP ~homoscedastic (~4ps floor); TNS strongly heteroscedastic
The worst-path metric effCP carries $\sigma\approx3$--$5$\,ps regardless of clock...
```

Grepping `% >>` must reproduce the paper's outline top to bottom. When adding or
moving a paragraph, add/move its comment too. When a paragraph's content drifts
from its comment, one of them is wrong — fix it (usually the paragraph).

## Rule 3 — Every table column and plot axis carries units

No bare numbers. Every quantitative table column and every plot axis states its
unit (ps, %, mW, µm², seeds, count, Pearson $r$, …). Dimensionless quantities say
so explicitly (a `(count)`, `(ratio)`, `($r$)`, or `(normalized)` label), so the
reader never has to guess whether a number is picoseconds or percent.

- Put units in the column header (a units row under the names) or append to the
  label — never leave them only in the caption or body.
- If a table mixes composite/derived units, name the unit explicitly (e.g.
  "PPA-cost units", "% vs.\ default") in the header, not just the caption.
- Plots: both axes labeled with quantity **and** unit; a legend if >1 series.

Before finishing any table or figure, scan every column/axis and confirm each has
a unit. A number without a unit is a bug.

## Rule 4 — References are consistent and compact

Bibliographies drift into inconsistency; keep every entry to one house style.

- **Author names: first initial(s) + surname only** (`B. Letham`, not
  `Benjamin Letham`). Apply it to every author, every entry.
- **Many authors: use ``et al.''** Do not list six names; the first author plus
  ``et al.'' saves space and reads cleanly. (For a strict venue rule, follow it;
  otherwise et al. past ~3 authors.)
- **Venues: one consistent convention.** Either a bare acronym (`ICCAD`, `DAC`,
  `ISPD`) when space is tight, or full name with acronym when space allows
  (`International Conference on Computer-Aided Design (ICCAD)`). Pick one per paper
  and use it for every entry — never mix bare-acronym and full-name across the list.
- **Drop boilerplate prefixes.** Omit `ACM/IEEE`, `Proceedings of the`, `In Proc.\
  of the` where they add nothing — `in \textit{Proc. ICCAD}, 2021` or just
  `ICCAD, 2021`, consistently.
- Consistent field order and punctuation across all entries (authors, ``title,''
  venue, year). If one entry has a volume/number, format volumes the same way
  everywhere they appear.

Before finishing, read the reference list top to bottom as a block and check that
names, venues, and prefixes all follow the same pattern.

## Workflow

- Compile-check with `pdflatex` before committing; remove build artifacts
  (`*.aux *.log *.pdf *.out`) so they aren't committed.
- Commit as the paper's author (no AI/Claude attribution, no `Co-Authored-By`),
  `git commit -s`.
- If the paper is an Overleaf git repo, **always push after committing** — do not
  ask each time.
