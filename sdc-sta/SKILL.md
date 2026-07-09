---
name: sdc-sta
description: Reference for OpenSTA and SDC timing commands. Use when writing .sdc constraint files, debugging timing with report_checks, setting up multi-corner/multi-mode analysis, or looking up the exact options for commands like create_clock, set_input_delay, set_false_path, set_multicycle_path, report_checks, set_timing_derate, etc.
argument-hint: "[command-name]"
---

# OpenSTA / SDC Command Reference

This skill fills the STA/SDC gap noted in `openroad-tcl`: OpenROAD itself does not ship structured markdown for SDC commands because those come from OpenSTA. The canonical reference is the OpenSTA user guide PDF, mirrored locally under `refs/`.

The mirrored files are from [parallaxsw/OpenSTA](https://github.com/parallaxsw/OpenSTA) and are distributed under the GPLv3 license (see `refs/LICENSE`).

## When to use this skill

- Writing or editing `.sdc` files or Tcl constraint scripts
- Looking up argument signatures for `create_clock`, `create_generated_clock`, `set_input_delay`, `set_output_delay`, `set_clock_groups`, `set_clock_uncertainty`, `set_clock_latency`, `set_false_path`, `set_multicycle_path`, `set_max_delay`, `set_min_delay`, `set_disable_timing`, `set_case_analysis`, `set_load`, `set_driving_cell`, `set_timing_derate`, …
- Debugging timing: choosing the right `report_checks` flags (`-path_delay`, `-group_path_count`, `-format`, `-fields`, `-from/-to/-through`)
- Multi-corner / multi-mode analysis (`define_corners`, `define_scene`, `read_sdc -mode`, `report_checks -scenes`)
- "Why does OpenSTA report no paths?" / "Why is this endpoint unconstrained?"
- Filter expressions (`get_cells`, `get_pins`, `get_nets`, `get_ports`, `get_clocks`, `-filter` syntax)
- OpenSTA variables (`sta_crpr_enabled`, `sta_dynamic_loop_breaking`, etc.)

## Primary reference: OpenSTA.pdf

`refs/OpenSTA.pdf` is the OpenSTA user guide (95 pages). Read it with the Read tool using the `pages` parameter — do **not** try to read the whole file at once.

Section → page map (from the ToC):

| Section | Pages |
|---|---|
| Command Line Arguments | 1 |
| Example Command Scripts | 1–5 |
| TCL Interpreter | 5 |
| Debugging Timing (no paths found / unconstrained endpoint) | 6–7 |
| **Commands** (full command reference, alphabetical-ish by category) | **7–83** |
| Filter Expressions | 84 |
| Variables | 85–95 |

Typical usage: if the user asks about, say, `set_multicycle_path`, read `refs/OpenSTA.pdf` with `pages: "7-40"` (or narrower once you've seen the ToC) and locate the command. The Commands section groups commands by topic (clocks → I/O delays → exceptions → reporting → parasitics → power).

## Secondary references

- `refs/README.md` — top-level OpenSTA README: build instructions, supported file formats, quickstart.
- `refs/Sta.tcl` — Tcl-level command wrappers. Grep here for `define_cmd_args "<name>"` to get an exact argument signature for commands defined at the Tcl layer (e.g., `define_scene`, `get_fanin`, `get_fanout`, `report_clock_properties`).
- `refs/Variables.tcl` — lists OpenSTA-specific Tcl variables you can set to change analysis behavior.
- `refs/Property.tcl` — object properties usable in `get_property` and in `-filter` expressions.
- `refs/CmdArgs.tcl` — argument-parsing helpers (not command definitions; read if you need to understand how flags are parsed).

Most SDC commands themselves (`create_clock`, `set_input_delay`, etc.) are implemented in C++ and registered via SWIG, so they do **not** appear in the `.tcl` files. For those, the PDF is authoritative.

## How OpenSTA relates to OpenROAD

When you run OpenROAD, OpenSTA is linked in and all SDC/STA commands are available at the OpenROAD Tcl prompt. So in an OpenROAD script you can freely mix:

```tcl
# OpenROAD commands (see openroad-tcl skill)
read_lef   tech.lef
read_lef   cells.lef
read_def   design.def

# OpenSTA/SDC commands (this skill)
read_liberty  cells.lib
create_clock -name clk -period 1.0 [get_ports clk]
set_input_delay  -clock clk 0.2 [all_inputs]
set_output_delay -clock clk 0.2 [all_outputs]
report_checks -path_delay min_max -format full_clock_expanded
```

The resizer module (`rsz` in the openroad-tcl skill) wraps timing-aware flows (`repair_timing`, `repair_design`) that drive OpenSTA under the hood, so for those commands prefer the `rsz.md` reference in the openroad-tcl skill.

## Quick lookup by task

| Task | Command(s) |
|---|---|
| Define a clock on a port | `create_clock -name <n> -period <p> [get_ports <port>]` |
| Define a divided / gated clock | `create_generated_clock -name <n> -source <src_pin> -divide_by <N> <target_pin>` |
| I/O timing | `set_input_delay -clock <clk> <val> [get_ports ...]`, `set_output_delay` |
| Async clock domains | `set_clock_groups -asynchronous -group {clkA} -group {clkB}` |
| Clock skew / jitter | `set_clock_uncertainty`, `set_clock_latency` |
| Ignore a path | `set_false_path -from ... -to ...` |
| Allow N cycles | `set_multicycle_path N -setup -from ... -to ...` (usually pair with `-hold N-1`) |
| Hard delay limit | `set_max_delay`, `set_min_delay` |
| Constant tie-off for analysis | `set_case_analysis 0|1 <pin>` |
| Disable a timing arc | `set_disable_timing <cell_or_pin>` |
| OCV derating | `set_timing_derate -early <f> -late <f> [-cell_delay] [-net_delay]` |
| Output load / input drive | `set_load`, `set_driving_cell` |
| Report timing | `report_checks -path_delay min_max -format full_clock_expanded -fields {slew cap input_pins nets fanout} -group_path_count <N>` |
| Report a specific endpoint | `report_checks -to [get_pins <pin>] -unconstrained` |
| Unconstrained endpoints | `report_checks -unconstrained`, `check_setup` |
| Clock report | `report_clock_properties`, `report_clock_min_period` |
| Power | `report_power` |

For exact arguments on any of the above, open `refs/OpenSTA.pdf` at the Commands section (starts page 7).

## Debugging "no paths found"

The PDF has a dedicated section (pages 6–7). Common causes:
1. No clock defined → `create_clock` first.
2. Endpoints unconstrained → missing `set_input_delay` / `set_output_delay`.
3. Path is disabled → check `set_false_path`, `set_disable_timing`, `set_case_analysis`.
4. Wrong object → confirm `get_pins` vs `get_ports` vs `get_nets`; use `report_object_full_names`.
5. Clock doesn't propagate → gated/generated clocks need `create_generated_clock` or `set_clock_sense`.

Always run `check_setup` early — it reports unconstrained endpoints, missing clocks, and combinational loops.

## Filter expressions

OpenSTA uses SDC-compatible filter syntax on collection commands:

```tcl
get_cells   -filter "ref_name =~ BUF*"
get_pins    -filter "direction == output && is_clock_pin == 1"
get_nets    -of_objects [get_cells U1]
all_registers -clock [get_clocks clk]
```

See `refs/OpenSTA.pdf` page 84 for the full filter grammar, and `refs/Property.tcl` for which properties are queryable per object type.

## Refreshing the local snapshot

```bash
cd .claude/skills/sdc-sta/refs
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/doc/OpenSTA.pdf     -o OpenSTA.pdf
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/README.md           -o README.md
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/tcl/Sta.tcl         -o Sta.tcl
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/tcl/CmdArgs.tcl     -o CmdArgs.tcl
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/tcl/Variables.tcl   -o Variables.tcl
curl -sf https://raw.githubusercontent.com/parallaxsw/OpenSTA/master/tcl/Property.tcl    -o Property.tcl
```

## Scope note

OpenSTA implements the subset of SDC needed for static timing analysis. Commands or flags that exist in other commercial STA tools but aren't in the OpenSTA PDF are generally not supported. The OpenSTA PDF defines the actual behavior you'll get.
