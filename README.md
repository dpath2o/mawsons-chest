# mawsons-chest

`mawsons-chest` is a research code repository for streamlined CICE analysis workflows, with a current focus on working from ice-history-style outputs and building reusable plotting, classification, metrics, and comparison tooling.

At the moment the repository is centered on two main code areas:

- **`nilas/`** — lightweight notebook-oriented tools for inspecting and plotting CICE history output.
- **`shuga/`** — a more structured package for classification, metrics, plotting, observations, and shared workflow utilities.

The project is under active development and is evolving toward a cleaner split between:
- reusable package code
- command-line / PBS workflow scripts
- notebook examples
- heavier observational and comparison workflows

## Repository structure

```text
mawsons-chest/
├── nilas/
│   ├── cice_netcdf_tools.py
│   ├── docs/
│   ├── notebooks/
│   └── README.md
└── shuga/
    ├── classify/
    ├── core/
    ├── docs/
    ├── io/
    ├── metrics/
    ├── notebooks/
    ├── observations/
    ├── plotting/
    ├── regridding/
    ├── scripts/
    ├── pyproject.toml
    └── README.md
```

## What this repo is for

This repository is intended to support practical Antarctic sea-ice analysis workflows, especially for CICE-based experiments run on NCI Gadi.

Typical use cases include:

- loading and inspecting CICE history output
- classifying landfast / fast ice from model diagnostics
- computing hemispheric and regional metrics
- plotting time series and maps from Zarr-backed workflows
- loading observational sea-ice products
- preparing model–observation comparison products

The long-term aim is to move away from one-off analysis scripts and toward reusable, better-structured modules.

## Components

### `nilas`

`nilas` is the lightweight side of the repository.

It is useful for:
- exploratory work in notebooks
- simple map and time-slice plotting
- quick inspection of CICE variables from history files
- prototyping figure ideas before moving them into more formal workflows

### `shuga`

`shuga` is the main workflow package currently under active development.

It is intended to provide:

- shared path and naming conventions
- reusable dataclasses and configuration objects
- classification workflows
- metrics workflows
- plotting workflows
- observational data loaders
- regridding and comparison utilities

The goal is that all workflow stages use the same directory and naming logic, so outputs from one stage can be consumed cleanly by the next.

## Installation

For development, install `shuga` in editable mode from the repo root:

```bash
cd /home/581/da1339/AFIM/src/mawsons-chest/shuga
pip install -e .
```

If you are working primarily in notebooks, this is the cleanest way to make `shuga` importable without manually editing `sys.path`.

## Current workflow style

The repository currently supports a mix of:

- notebook-driven exploration
- direct Python usage
- command-line scripts
- PBS wrapper workflows for Gadi

In practice, the newer development direction is to keep the reusable logic inside `shuga`, and keep scripts as thin entry points.

## Recommended starting points

If you are new to the repo, a good sequence is:

1. read `nilas/README.md`
2. read `shuga/README.md`
3. check `shuga/docs/quickstart.md`
4. open the example notebooks under `nilas/notebooks/` and `shuga/notebooks/`

## Development notes

This is an active research repository, not a frozen software release. Interfaces, paths, and conventions may change as the package structure is cleaned up and comparison workflows are moved into more reusable modules.

A few practical assumptions are currently baked into parts of the codebase:

- NCI Gadi as the main runtime environment
- AFIM / CICE-oriented file layouts
- user and project defaults for `/g/data/...` paths
- Zarr-backed intermediate products for some workflows
- large observational products stored outside the repo itself

## What should not live in the repository

This repository should contain source code, notebooks, light documentation, and small configuration assets.

It should generally **not** contain:

- large model outputs
- Zarr stores
- NetCDF archives
- generated figures and animations
- scratch products
- PBS log files
- local cache directories

Those are better kept in `/g/data`, `/scratch`, or user-specific analysis output locations.

## Status

The public repository currently exposes `nilas/` and `shuga/` as the main top-level directories, and the repo description describes the project as streamlined CICE analysis on ice history files. This README is intended to give that structure a clearer entry point while the package layout is still being expanded.

## Author

Daniel Patrick Atwater

## License

Add a repository license here when ready.
