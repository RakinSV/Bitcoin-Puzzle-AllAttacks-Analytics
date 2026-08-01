# A numbering trap in `unsolvedpuzzles.txt` (and how to verify your own table)

**Short version:** if you built a puzzle-number → address table by reading
keyhunt's `tests/unsolvedpuzzles.txt` positionally — *"line N is puzzle N+66"* —
your high puzzles are almost certainly mislabelled, by up to **+10**. This is not
a bug in keyhunt. The file is exactly what its name says: a list of *unsolved*
puzzles. The mistake is treating a filtered list as a contiguous range.

We shipped that mistake for several releases. This note exists so the next person
doesn't.

## What goes wrong

The puzzle series runs 1…160, but the creator exposed public keys for the
multiples of five, and solvers took them. By the time `unsolvedpuzzles.txt` was
written, ten of those — **75, 80, 85, 90, 95, 100, 105, 110, 115, 120** — were
already solved, so they are simply **absent** from the file.

Positional indexing therefore drifts by +1 at each missing entry:

| line | you assume | actually is |
|---|---|---|
| 1 | 71 | 71 ✔ |
| 4 | 74 | 74 ✔ |
| 5 | **75** | **76** ✗ |
| 10 | **80** | **82** ✗ |
| 55 | **125** | **135** ✗ |
| 80 | **150** | **160** ✗ |

The drift accumulates to +10 and then stays there, because after 120 every
remaining puzzle is unsolved and nothing else is skipped.

## The proof

Puzzle #135's private key was published when it was solved
(`0x6D9392A16883F90903D5F78DA57AF07EB2`). It is 135 bits, it lies inside
`[2^134, 2^135)`, and it derives to:

```
16RGFo6hjq9ym6Pj7N5H7L1NR1rVPJyw2v
```

which is the address a positional table labels **#125**. One derivation settles
it — no trust required.

## How to check your own table in one line of reasoning

Puzzle *N* is funded with exactly **N × 0.1 BTC**. That makes the funded amount a
self-verifying label:

```
true_puzzle_number = round(funded_BTC × 10)
```

#71 holds 7.1 BTC, #135 holds 13.5 BTC, #160 holds 16.0 BTC. Query each address
once and compare. This repo does it in `analysis/verify_registry.py`:

```bash
python analysis/verify_registry.py --max 160
```

It prints every mismatch with the correct number. Note the heuristic only holds
from #71 up — the early puzzles were funded differently (and topped up in 2023),
so verify those against their known private keys instead.

## Why it matters

Everything downstream inherits the error, silently and plausibly:

- **Interval bounds.** Puzzle *N* is searched over `[2^(N-1), 2^N)`. A +10 label
  error means searching a range that is **1024× too small** and cannot contain
  the key — the search simply never succeeds, and looks like bad luck.
- **Feasibility estimates.** Kangaroo costs `K·√(2^(N-1))`. Reporting #125 when
  the target is #135 understates the work by a factor of 32.
- **Target selection.** We had reported #125–150 as "unsolved with exposed
  pubkey". Those are really **#135–160** — larger, and further out of reach than
  we had told ourselves.

The addresses were never wrong; only the numbers attached to them were. That is
what made it survive so long: every individual address looked fine.

## Fixed here

`utils/puzzle_registry.py` is now labelled from the chain rather than from line
numbers, and `analysis/verify_registry.py` re-checks it on demand. Puzzles
75, 80, … 120 carry no entry, because that source never contained them — they are
all solved, so nothing searchable depends on them.
