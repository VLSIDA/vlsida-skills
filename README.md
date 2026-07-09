# VLSIDA Claude Code Skills

Claude Code skills developed by the [VLSIDA lab](https://vlsida.github.io/) at UC Santa Cruz.
These skills extend [Claude Code](https://claude.ai/code) with domain-specific knowledge for EDA tooling, cloud infrastructure, and research computing.

## What are Claude Code skills?

Skills are context documents that Claude Code loads on demand to gain specialized knowledge or capabilities. Install them by cloning this repo into `~/.claude/skills/`.

## Installation

```bash
git clone https://github.com/VLSIDA/vlsida-skills ~/.claude/skills/vlsida-skills
```

Then register each skill you want in your `~/.claude/settings.json`:

```json
{
  "skills": [
    "~/.claude/skills/vlsida-skills/openroad-tcl",
    "~/.claude/skills/vlsida-skills/sdc-sta",
    "~/.claude/skills/vlsida-skills/nautilus-nrp",
    "~/.claude/skills/vlsida-skills/gcloud"
  ]
}
```

## Skills

### EDA / Physical Design

| Skill | Description |
|---|---|
| [`openroad-tcl`](openroad-tcl/) | Offline reference for OpenROAD Tcl commands and arguments. Covers all modules: global/detailed placement, routing, CTS, PDN, floorplan, pin placement, IR drop analysis, and more. Use when writing OpenROAD flow scripts or looking up exact command syntax. |
| [`sdc-sta`](sdc-sta/) | Reference for OpenSTA and SDC timing commands. Covers `create_clock`, `set_input_delay`, `set_false_path`, `set_multicycle_path`, `report_checks`, multi-corner analysis, and debugging unconstrained paths. Includes a local mirror of the OpenSTA user guide PDF. |

### Cloud / Research Computing

| Skill | Description |
|---|---|
| [`nautilus-nrp`](nautilus-nrp/) | Kubernetes job and storage management on the [National Research Platform (NRP) Nautilus](https://nationalresearchplatform.org/nautilus/) cluster. Includes batch job templates, interactive pod setup, and PVC-based persistent storage patterns. |
| [`gcloud`](gcloud/) | Google Cloud Platform via the `gcloud` CLI. Covers authentication, GCS bucket management, file transfers, GCE VM lifecycle, SSH, disks, and firewall rules. |

## License

BSD 3-Clause License. See [LICENSE](LICENSE).

Some skills include reference material mirrored from upstream open-source projects under their own licenses — see the `refs/LICENSE` file within each skill directory for details.
