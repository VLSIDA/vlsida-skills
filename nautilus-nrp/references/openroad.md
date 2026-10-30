# OpenROAD / ORFS on Nautilus

Apply this reference only for an OpenROAD workload, alongside that checkout's
AGENTS.md/CLAUDE.md, development protocol and shared memories. Repository rules
own source-of-truth installation sync, test-first requirements, versions and
experiment presentation. A Nautilus skill does not authorize a solver fix,
version bump, commit, new scientific trial or change to an existing comparison.

## Freeze the scientific experiment

Record source version/tree hash, OpenROAD binary and extension hashes, immutable
image/worker/manifest, PDK/design input hashes, seed, flow settings and requested
endpoint per case. Keep resource scheduling changes separately labelled. Do not
mix a PDN/halo/core/optimizer change into a parameter sweep to make failures go
away. A retained flow failure belongs in the original denominator and is not
replaced with a favorable seed. Matched seeds and independent parameter sweeps
remain distinct; repeated controls are not extra independent samples. Five or
ten seeds alone do not establish significance or remove multiple-comparison bias.

Do not assume runtime comparisons are controlled when nodes, CPU allocation,
setup, I/O or phase-pool shapes differ. Record application compute time,
bootstrap time, phase walltime, queue delay and infrastructure interruptions
separately. Solver-quality evidence and scheduling-throughput evidence differ.

## Phase pools and endpoints

A useful ORFS split, when these stage names exist in the frozen checkout:

| Pool | Work | Required handoff |
|---|---|---|
| Base | Synthesis / 2_1_floorplan | Exact base-input hashes and completion |
| Place | 2_2 macro placement through 4_cts | Case-specific place receipt, CTS marker and ODB |
| GRT | 5_1_grt only for a GRT study | Verified predecessor and original seed/settings |
| Detailed route / final | Requested later stages through 6_final/6_report | Explicit authorization and upstream receipts |

Stage naming and dependencies vary by ORFS version: inspect that checkout's
flow targets rather than assuming this table is universal. Enforce the requested
stop in the worker, validate the produced endpoint and never run detailed route
just because an ODB exists. A GRT result is not a completed route or signoff.

Measure phase-specific cgroup peaks and child RSS. In one 2026 study, completed
eyeriss/partition_c GRT phases sampled roughly 7–11 GiB cgroup peaks although
early samples were only around 1–2 GiB. These are historical design-specific
measurements, not default resource values. Do not cap a GRT worker at its early
memory sample. MPL/SA and some routing portions have serial tails: NUM_CORES
does not guarantee sustained utilization of every requested core.

## Long steps and memory ramps on large designs

A design an order of magnitude larger changes the scheduling, not only the
resource numbers. bp_quad (about 2.5M instances, nangate45) in one 2026-10
study:

- Global routing ran a median 1.9 h (max 5.2 h, 155 steps) with peak RSS of
  52–96 GiB, so its Pods requested 111 GiB with limit equal to request. RAM
  stayed near 11–12% of the request while the router loaded and reached 20%
  after a median 44 minutes. Each such Pod is outside NRP's RAM band for most
  of an hour, and resizing cannot fix that because the request is the peak.
  The study admitted these steps through a few routing "ramp slots" (2, later
  3), trading the length of the tail against the account's out-of-band count.
  A simulation of its arrival rate put the last routing step about 28 h out
  with 2 slots and 21 h with 3.
- Global placement outgrew the study's first 12 h step limit. The limit for
  that step was raised to 24 h, and every case the 12 h limit had killed was
  rerun (see "Changing a step limit mid-study" in the orchestration
  reference). Without hierarchy, placements then ran from 9 to more than 19
  hours, and two reached 24 h and count as timeouts.
- Logs grow large: one 6 h macro-placement timeout left a 90 MB make output.
  Collectors read tails, never whole logs.

Measure the longest normal step per design and phase on a pilot before
freezing step limits, request sizes and ramp-slot counts.

## Diagnose by actual stage and error

| Evidence | What to investigate |
|---|---|
| PDN-0179 / PDN-0178 at power-grid generation | Supply-channel repair against actual macro geometry, grid and repair markers |
| MPL-0989 / core-fit stop | Whether the solve fits under the current area/shape constraints; failure is not proof of mathematical infeasibility |
| GRT-0116 / congestion stop | Native routing congestion, overflow/capacity and the failed stage's outputs |
| OOMKilled native container | Resource-profile hold; no inferred solver defect or automatic retry |
| exit 255 / Unknown across a common node | Node/runtime/collection evidence; do not label a scientific failure from this alone |
| Missing terminal Pod/stdout | Collection hold; preserve cached logs as unverified |

Failure text comes from files the failing attempt closed. ORFS's `flow.sh`
writes each step's log as `<step>.tmp.log` and renames it to `<step>.log` when
the step's subshell exits, so a killed step can leave either name. A saved make
output (`make_<step>.out`) holds make's own error and a timeout's "Terminated"
line. One study searched the attempt's own folder (named by the attempt id in
the Job name), then the run's state folder, then both log names. It read at
most the last 8 MB of each file, kept lines matching `[ERROR XXX-nnnn]`,
tracebacks, make's `*** [` and kill or timeout words, kept a 40-line tail,
and recorded each file's size, SHA-256 and whether only the tail was read.
For tables, group first-error lines that differ only in numbers (coordinates,
sizes, counts) under one key: 156 Vastu macro-placement failures then formed
one MPL-0989 row.

Parameter-predicted routing utilization is not automatically the router's
capacity or placement-density knob. Record configured and realized values from
the actual frozen hook/predictor and per-run census. If a model uses Rent-p and
GR_UTIL, keep independent sweeps independent and state what each parameter
changes. Do not substitute a different formula from another solver version.

Node problems need dated, evidenced quarantine entries, not a universal deny-list.
A single crash on one node does not establish the cause; any same-seed rerun
must follow the study's existing infrastructure/scientific retry policy.

## Congestion from the saved global-routing grid

[`examples/gcell_dump.tcl`](../examples/gcell_dump.tcl) dumps, per GCell, the
maximum over routing layers of usage/capacity that global routing stored in
the ODB (no re-routing), plus the macro outlines.
[`scripts/gcell_stats.py`](../scripts/gcell_stats.py) summarizes all GCells and
the GCells outside macros. Measured on 1,395 routed nangate45 runs (2026-10,
ORFS default global routing):

- The grid stores macro-blocked tracks as usage, so every GCell touching a
  macro reads exactly 1.0. Macros covered 4–70% of the GCells, depending on the
  design, so statistics over all GCells mostly measure macro area. Compare arms
  on the GCells outside macros.
- Overflow (above 1.0) was zero in every run. Under ORFS's default
  `GLOBAL_ROUTE_ARGS` a global route finishes only after resolving overflow;
  otherwise the step fails with GRT-0116 (`-allow_congestion` or the CUGR
  router turn that into warning GRT-0115). Overflow therefore cannot rank
  finished runs; report routing failures as failures.
- The outside-macro p95 took only 12 distinct values, and half the runs had
  exactly 1.0, because capacities are small track counts. 77% of the
  arm-versus-reference pairs (same design, setting and seed) had identical
  p95, while every pair differed in the share of GCells at 0.9 or more. Compare
  the shares at 0.9 or more and at 0.99 or more.
- A flow that deletes `5_1_grt.odb` after detailed routing still carries the
  grid in `6_final.odb`. Record which checkpoint each map came from and its
  SHA-256, checked against the run's own committed hash when there is one.
- The grid had 0.1229 GCells per µm² of die on every design (pitch 2.85 µm),
  so its size is known from the die area before the dump.
- `getGridX`/`getGridY` list GCell origins, and the last GCell runs on to the
  die edge (gcd: 12 origins from 0 to 31.35 µm, die 36.725 µm). The pitch is
  therefore (last − first) / (n − 1). That study's tools divided by n, so their
  macro mask drifted by up to one GCell toward the far edges. On saved dumps
  this left 0.1–0.4% of the GCells misclassified, mostly macro-edge GCells
  reading 1.0, and raised cnn's outside-macro share at 0.99 or more from about
  0.32% to 0.37%. `scripts/gcell_stats.py` uses the origin convention.
- Peak RSS follows the ODB file, not the GCell count. It was 1.6–3.8 times the
  ODB size (median 2.6) over 1,149 `5_1_grt` dumps and 2.8–3.7 times (median
  3.2) over 42 `6_final` dumps, whose detailed routes enlarge the ODB.
  bp_quad's 3.1–3.5 GB ODBs needed 7.2–7.9 GB. Time was a median 34 s per
  million GCells (2–5 minutes for bp_quad's 4–8 million), varying about 9-fold
  between runs.

## Figures and interactive reports

The live monitor accepts reported metrics and artifact links; generation of real
EDA figures remains in the authorized execution environment. For Nautilus-only
work, run OpenROAD, renderers requiring OpenROAD and scientific sweeps there;
keep the host for lightweight orchestration and HTML. Inspect closed stage
artifacts only; do not bulk-export live ODB/log trees from another Pod.

Use the project's existing visual tools and consistent instance/cluster mapping
across arms of a design. In the Vastu ORFS checkout that informed this skill:

- `vastu_setup/experiments/cluster_movement_compare.py` provides cluster-colored
  seed/final comparisons; use the same inst→cluster mapping for all placers.
  That checkout requests `--no-legend`, and rtlmp seed inflation uses its
  `--inflate-cells-for rtlmp=20` convention.
- The local experiment convention is a triptych named
  `<design>_<arm>_{seed,final,routed}.png`: cluster movement at 2_2 and 3_5,
  plus a real 6_final GUI shot through `odb_to_png.sh`. The 2_2 cluster shot
  replaces a separate macro-only seed image. Omit images for stages not reached;
  a GRT-only run therefore has no fabricated 6_final routed image.
- Native Vastu `reports/<pdk>/<design>/<arm>/vastu/floorplan.html` belongs under
  the experiment's `images/htmlviz/` as gzip, separate from those three images.
- Add actual GRT congestion maps, including for completed runs beyond GRT when
  their relevant stage data is retained. Label stage/layer, units and whether
  the map is estimated demand or actual router congestion; compare arms on
  consistent scales. Do not label an estimated heatmap as measured overflow.
  See the congestion section above for what the saved grid does and does not
  measure.
- Keep the complete story—metrics, runtimes, failures, per-design/seed evidence
  and per-run images—in the experiment README and interactive HTML according
  to project rules. Images/htmlviz are results; large raw logs belong in the
  project's separate log directory.

Rendering costs and checks from that checkout's 2026-10 study:

- Seed and final cluster-movement images took a median 20–100 s and 0.5–1.7 GB
  RSS per run on its seven smaller designs, which fit NRP's exempt 1 CPU and
  2 GB Pods. bp_quad needed a median 20 minutes and 13 GB per run, plus a
  612 MB colour-map JSON, so those ran in 2 CPU and 32 GB Pods after the
  study's last worker finished.
- Judge an image by a fresh, non-empty file in an empty output directory.
  `cluster_movement_compare.py` only warns about OpenROAD's exit code and keeps
  the PNG; `odb_to_png.sh` discards the status and checks only that the file
  exists. A PNG left from an earlier attempt would hide a failure.
- Use one inst-to-cluster mapping per design for all arms, taken from a fixed
  reference run, and record its SHA-256 with every image.
- Vastu's `floorplan.html` was 2.6–19.5 MB per run (bp_quad 85–156 MB).
  `gzip -9 -n` shrank it to 1.6–9.6% and is deterministic, so parts exported by
  different Pods join byte for byte (`examples/stdout_export.sh`).

Those file paths and triptych rules are repository conventions, not universal
OpenROAD requirements. For another project, discover its own tools and format.
The generic dashboard can display die shots, congestion maps, loss curves,
simulation plots or any other authorized artifact using the same link schema.
