---
name: paper-writing
description: Conventions for writing and editing academic papers (LaTeX). Enforces captions that state the conclusion (not describe the table), a topic comment before every paragraph, units on every table column and plot axis, consistent compact references, an abstract that answers problem/difficulty/approach/results, a motivating Figure 1, and human-authored style with AI used only to polish (no AI tells). Use whenever creating or editing paper .tex source.
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

## Rule 2 — Outline mode: every block has a topic comment, and the comments are the paper

Immediately before **every** section, subsection, and paragraph, put a LaTeX
comment stating that block's single argument. Together, these comments are the
paper's living outline. They serve two jobs at once:

1. **Local discipline** — each paragraph is anchored to one claim, so it cannot
   quietly grow a second topic.
2. **Global argument** — grepping the comments in reading order reproduces the
   paper's argument as coherent prose. You can read the outline aloud and hear
   whether the paper works.

### Format

```
% >> <LOCATOR>[ [FLOAT]]: <one-sentence argument this block makes>
```

- **`<LOCATOR>`** — a hierarchical tag that sorts into reading order. Pick one
  numbering style per paper (arabic or roman) and use it everywhere:
  - `4` — section 4
  - `4.p1` — section 4, paragraph 1 (`p` for paragraph)
  - `4.2` — subsection 4.2
  - `4.2.p1` — subsection 4.2, paragraph 1
  - `4.2.1.p3` — deeper nesting extends the same pattern
- **`[FLOAT]`** *(optional)* — the label of a figure or table this paragraph
  anchors: `[fig:overview]`, `[tab:results]`. So a reader scanning the outline
  sees exactly where each float is introduced.
- **`<one-sentence argument>`** — a full sentence stating *what the paragraph
  asserts*, not a topic label. Not `power analysis`; rather
  `Power falls as designs correlate, so the plan must measure correlation before
  choosing the sample size.` A topic label ("power analysis") can hide a broken
  argument; a full sentence fails visibly when the argument is missing or when
  two paragraphs assert the same thing.

If you cannot compress the paragraph's argument into one sentence, the paragraph
is doing too much — split it.

Example (in-file):
```latex
% >> 3.2: A trace-driven simulator misses effects that only appear on real hardware, so the study checks every prediction against on-die counters.
\subsection{Validating the simulator}

% >> 3.2.p1 [fig:gap]: On five benchmarks the predicted and measured miss rates diverge by more than the effect the paper studies, so simulation alone cannot decide the study.
The simulator replays a filtered trace...
```

### Outline mode: write the outline first, prose second

Reorganizing an outline is cheap; reorganizing prose is expensive. Work in this order:

1. **Draft the outline for a section** — write the `% >> ` comments in order,
   one per intended paragraph, before writing any prose.
2. **Read the outline aloud.** If it does not flow as an argument, fix the
   outline. Add missing links, cut repetitions, resplit paragraphs that carry
   two claims. This is the cheapest structural edit you will ever make.
3. **Get alignment on the outline** — with coauthors, advisors, or reviewers
   pushing back on structure — before writing prose.
4. **Then write each paragraph** so that its prose asserts exactly the sentence
   above it, nothing more.

When a paragraph's argument later shifts under revision, update its topic
comment first, re-read the outline, then edit the prose to match.

### `get_outline.sh` — the paper as a document

Keep a small script at the repo root that greps `% >> ` from every section
file, in reading order:

```bash
#!/bin/bash
grep "% >>" sections/intro.tex
grep "% >>" sections/related.tex
grep "% >>" sections/methods.tex
grep "% >>" sections/experiments.tex
grep "% >>" sections/conclusion.tex
```

Running it must print a document you can read as the paper's argument. Run it
before any structural commit, and any time a reviewer questions the flow.

### Invariants

- **Complete.** Every section, subsection, and paragraph has exactly one topic
  comment. Adding a paragraph means adding its comment first.
- **Truthful.** When comment and prose disagree, one of them is wrong; almost
  always the prose has drifted, and either the prose or the comment needs to
  change so they match.
- **In order.** Locators sort into reading order. Moving a paragraph means
  renumbering it and everything after it.
- **Preserved when cut.** When you comment out a paragraph but might revisit
  it, comment out its topic line too by adding an extra `%` (`%% >> 4.2.p3: ...`).
  The slot stays visible in the outline as a decision to be revisited, rather
  than silently disappearing.
- **Audited before commit.** Run `./get_outline.sh` and read it end-to-end.
  If a section jumps, repeats, or skips a step, fix the argument in the outline
  before touching prose.

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

## Rule 5 — The abstract answers four questions, in order

An abstract is not a summary of the sections; it is a self-contained argument that
makes a reader decide the paper is worth reading. Write it to answer four things,
in this order, each in roughly one to three sentences:

1. **The problem.** What is wrong or missing? State the gap concretely, not
   "X is important." The first sentence should name the problem, not the background.
2. **Why it is difficult.** Why doesn't the obvious/prior approach already solve it?
   Name the specific obstacle that makes it hard — this is what justifies the paper.
3. **How we solved it, and why it differs from prior solutions.** The key idea in
   plain terms, plus the one thing that distinguishes it from what came before
   (the novelty). If a reader can't tell how this is different, the abstract failed.
4. **The high-level results.** The headline outcome — the numbers or findings a
   reader would quote. Be specific ("14--19\% PPA, no single recipe transfers"),
   not vague ("improves results"). An honest negative result is still a result.

Keep it tight (typically ~150--250 words) and free of citations, undefined
acronyms, and section cross-references. Every sentence should map to one of the four
questions; if a sentence answers none of them, cut it. Write the abstract last (or
rewrite it last), once the results are known, so it promises exactly what the paper
delivers.

## Rule 6 — Open with a motivating example (Figure 1)

A paper is far stronger when an early figure (usually Figure 1, on page 1–2) gives
the reader the whole idea before any machinery. Prefer to include one.

- **Show a toy problem or a preview of the result**, not the system architecture.
  A small, concrete instance the reader can hold in their head — the smallest thing
  that makes the problem real and the payoff visible.
- **It carries the intuition the rest of the paper formalizes.** After Figure 1 the
  reader should already know what the problem is, why it matters, and roughly what
  the paper does about it; the body then earns those claims rigorously.
- **Introduce new terminology here**, in context, where a picture anchors each new
  term — so later sections can use the vocabulary without re-defining it.
- **Motivate, don't summarize.** The figure answers "why should I care?" — a
  before/after, a failure case the method fixes, a worked mini-example — not a block
  diagram of the pipeline.
- Its caption still obeys Rule 1 (states the takeaway), and it is referenced from
  the introduction where the story first needs it.

When drafting a new paper, ask early whether such a figure exists; if not, propose
one. When editing, check that Figure 1 does this job rather than diving into detail.

## Rule 7 — Use AI to polish, but make the work your own

Using an AI assistant to refine wording, check grammar, tighten a sentence, or catch
a typo is fine. Using it to produce the substance is not: the ideas, the claims, the
framing, and the voice must be yours. Treat the model as a copy editor, never a
co-author, and read every suggested change critically before accepting it.

AI-generated prose has recognizable tells. Strip them so the text reads as a human
specialist wrote it:

- **No sensationalism.** Cut hype: "breakthrough," "revolutionary," "seamlessly,"
  "powerful," "cutting-edge," "game-changing," "remarkable," "vast." State claims
  plainly and back them with evidence, not adjectives.
- **No over-generalization.** The audience is expert reviewers in a narrow field, not
  a general reader. Do not explain basics they already know, do not open with broad
  throat-clearing ("In today's world of..."), and do not inflate a specific result
  into a sweeping one. A specialized paper is precise, not broad.
- **Fix the grammatical and typographic tells.** Replace em-dashes with commas,
  colons, or parentheses. Watch for other giveaways: "it is worth noting that,"
  "importantly," "delve," "underscore," "leverage" (as a verb), "a testament to,"
  the "not only X but also Y" and "X isn't just Y, it's Z" constructions, framing
  phrases like "the honest picture," "the honest situation," or "the real story is,"
  reflexive three-item lists, and hedges like "arguably" or "generally." Vary
  sentence length; AI tends to a monotonous medium-length rhythm.

Test: read a passage aloud. If it sounds like a polished press release rather than a
colleague explaining a result, revise it.

## Rule 8 — Titles are specific, distinctive, and honest

The title is the most-read and most-indexed part of the paper; it has to earn a read
and stand alone in a citation list.

- **Distinct titles for distinct papers.** Two papers on related work must have
  clearly different titles, or they get lumped together in search, indexing, and
  citations. A journal extension should not reuse its conference title: give it a new
  title that reflects the added contribution, so the two are treated as separate works
  and do not trip duplicate-submission or self-plagiarism checks.
- **Name the contribution, not just the topic.** "A Study of X" or "X in Y" says
  little; a title that states the result or the method is more informative and more
  citable. Front-load the terms a reader would search for.
- **Cut empty words.** Drop "Novel," "Efficient," "A Study of," "On the," and similar
  filler that every paper could claim. "Towards" is fine only when the work is
  genuinely preliminary.
- **Do not overclaim.** The title is a promise the paper must keep (Rule 7); avoid
  sweeping or sensational wording for a specialized result.
- **Consider a named artifact.** If the contribution is a tool or system, a short
  memorable name with a descriptive subtitle ("Name: what it does") is both
  distinctive and searchable, a common pattern in EDA.
- **Check uniqueness before finalizing.** Search the title (Scholar, DBLP); if it
  collides with existing work, sharpen it.

## Workflow

- Before any structural edit, run `./get_outline.sh` (Rule 2) and read the outline
  end-to-end; edit the outline first, then the prose.
- Compile-check with `pdflatex` before committing; remove build artifacts
  (`*.aux *.log *.pdf *.out`) so they aren't committed.
- Commit as the paper's author (no AI/Claude attribution, no `Co-Authored-By`),
  `git commit -s`.
- If the paper is an Overleaf git repo, **always push after committing** — do not
  ask each time.
