---
name: openroad-tcl
description: Reference for OpenROAD Tcl commands and their arguments. Use when writing OpenROAD Tcl scripts (io.tcl, pdn.tcl, save_image scripts, custom flow steps) or when looking up the exact options for a specific OpenROAD command.
argument-hint: "[command-name or module-name]"
---

# OpenROAD Tcl Command Reference

This skill provides offline access to the OpenROAD Tcl command reference. Each OpenROAD module (gpl, dpl, cts, drt, etc.) documents its commands in a `README.md` file in its source directory; those READMEs are mirrored here under `refs/`.

The mirrored files are from [The-OpenROAD-Project/OpenROAD](https://github.com/The-OpenROAD-Project/OpenROAD) and are distributed under the BSD 3-Clause License (see `refs/LICENSE`).

## When to use this skill

- Writing or editing an OpenROAD Tcl script (`io.tcl`, `pdn.tcl`, custom flow scripts, image generation scripts)
- Looking up the exact arguments and flags of a specific OpenROAD command
- Understanding what commands a particular module exposes
- Finding the right command for a task (e.g., "how do I add a power stripe?")

## How to use the references

1. **Find the right module file**. The references live in `refs/<module>.md`. Module mapping:

   | Module | Purpose | Notable commands |
   |--------|---------|------------------|
   | `_top.md` | Top-level module index | — |
   | `ant.md` | Antenna checker | `check_antennas`, `repair_antennas` |
   | `cts.md` | Clock tree synthesis | `clock_tree_synthesis`, `report_cts` |
   | `dft.md` | Design for test (scan) | `scan_replace`, `insert_dft` |
   | `dpl.md` | Detailed placement | `detailed_placement`, `optimize_mirroring` |
   | `drt.md` | Detailed routing (TritonRoute) | `detailed_route`, `set_routing_layers` |
   | `est.md` | Parasitic estimation | `estimate_parasitics` |
   | `fin.md` | Metal fill | `density_fill` |
   | `gpl.md` | Global placement | `global_placement`, `cluster_flops` |
   | `grt.md` | Global routing (FastRoute) | `global_route`, `set_global_routing_layer_adjustment` |
   | `gui.md` | GUI / image generation | `save_image`, `gui::set_heatmap`, `gui::set_display_controls` |
   | `ifp.md` | Initial floorplan | `initialize_floorplan`, `make_tracks` |
   | `mpl.md` | Macro placement (RTLMP) | `rtl_macro_placer`, `place_macro` |
   | `odb.md` | OpenDB database | `read_db`, `write_db`, `read_lef`, `read_def` |
   | `pad.md` | I/O pad placement | `place_pad`, `make_io_sites` |
   | `par.md` | Hypergraph partitioning | `triton_part_hypergraph`, `triton_part_design` |
   | `pdn.md` | Power delivery network | `add_pdn_stripe`, `add_pdn_connect`, `define_pdn_grid`, `add_global_connection` |
   | `ppl.md` | Pin placement | `place_pins`, `place_pin`, `define_pin_shape_pattern` |
   | `psm.md` | IR drop / power network analysis | `analyze_power_grid`, `check_power_grid` |
   | `rcx.md` | RC parasitic extraction | `extract_parasitics`, `write_spef` |
   | `rmp.md` | Restructure (logic remap) | `restructure` |
   | `rsz.md` | Resizer / repair | `repair_design`, `repair_timing`, `report_checks`, buffer insertion |
   | `stt.md` | Steiner tree | `set_routing_alpha` |
   | `tap.md` | Tapcell / endcap | `tapcell`, `cut_rows` |
   | `upf.md` | UPF power intent | `read_upf`, `write_upf` |
   | `utl.md` | Utility / logging | `report_metric`, message verbosity |

2. **Read the file** with the Read tool. Each README has a "Commands" section listing every command in that module with its full argument signature, description, and examples. Files are 200-700 lines each.

3. **Searching by command name**. If you don't know which module a command belongs to, grep for it across the references:
   ```
   Grep for "<command_name>" in path .claude/skills/openroad-tcl/refs/
   ```

4. **STA / SDC commands** (e.g., `create_clock`, `set_input_delay`, `report_checks`, `set_false_path`, `set_clock_uncertainty`) come from OpenSTA, not OpenROAD itself. OpenSTA does not publish a structured markdown reference — these are standard SDC commands documented in the Synopsys Design Constraints LRM. The `rsz.md` file documents `report_checks` and the resizer's timing-aware variants.

## When references look stale or incomplete

The files in `refs/` are snapshots from upstream `https://github.com/The-OpenROAD-Project/OpenROAD/tree/master/src/<module>/README.md`. If you encounter:

- A command that exists in OpenROAD but is not documented in the local snapshot
- Argument descriptions that don't match the behavior you observe
- A new module/command added upstream after the snapshot was taken

…then refresh the local snapshot from upstream:

```bash
cd .claude/skills/openroad-tcl/refs
for mod in ant cts dft dpl drt est fin gpl grt gui ifp mpl odb pad par pdn ppl psm rcx rmp rsz stt tap upf utl; do
  curl -sf "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD/master/src/$mod/README.md" -o "$mod.md"
done
curl -sf "https://raw.githubusercontent.com/The-OpenROAD-Project/OpenROAD/master/src/README.md" -o "_top.md"
```

After refreshing, re-read the relevant module file. If a brand-new module appears upstream that isn't in the list above, also add it to the loop.

## Notes on argument syntax

In the OpenROAD READMEs, command argument signatures use this convention:

- `[-flag value]` — optional flag with a value
- `[-flag]` — optional boolean flag
- `-required value` — required flag (no brackets)
- `arg` — positional argument

Example from `gpl.md`:
```tcl
global_placement
    [-timing_driven]
    [-routability_driven]
    [-density target_density]
    [-init_density_penalty init_density_penalty]
    ...
```

Most OpenROAD commands take all-keyword arguments (no positional ordering required).
