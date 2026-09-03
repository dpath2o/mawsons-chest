#!/bin/bash
set -euo pipefail

RUN_NAME=""
REFERENCE_SIM="Cs-high"
START_DATE=""
END_DATE=""
HISTORY_ROOT=""
AFIM_OUTPUT_ROOT=""
REFERENCE_ROOT=""
STATIC_STORE=""
PROJECT="gv90"
RUN_USER="da1339"
OVERWRITE="false"
SKIP_PROCESSING="false"
DRY_RUN="false"

usage() {
    cat <<'EOF'
Usage: ./run_health_check_pbs_wrapper.sh -s RUN_NAME [options]

Required:
  -s RUN_NAME       Candidate CICE run, e.g. frcg-exp01

Optional:
  -r REFERENCE      Reference simulation (default: Cs-high)
  -b START_DATE     YYYY-MM-DD; otherwise inferred from iceh filenames
  -e END_DATE       YYYY-MM-DD; otherwise inferred from iceh filenames
  -d HISTORY_ROOT   Candidate NetCDF history directory
  -A AFIM_ROOT      AFIM output root
  -R REF_ROOT       Explicit reference simulation root
  -S STATIC_STORE   Static CICE grid Zarr
  -P PROJECT        Data-path project (default: gv90)
  -U USER           Run owner (default: da1339)
  -o                Refresh candidate history/classification/metrics products
  -k                Skip candidate processing and compare existing products only
  -n                Dry run: print qsub command only
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -s) RUN_NAME="$2"; shift 2 ;;
        -r) REFERENCE_SIM="$2"; shift 2 ;;
        -b) START_DATE="$2"; shift 2 ;;
        -e) END_DATE="$2"; shift 2 ;;
        -d) HISTORY_ROOT="$2"; shift 2 ;;
        -A) AFIM_OUTPUT_ROOT="$2"; shift 2 ;;
        -R) REFERENCE_ROOT="$2"; shift 2 ;;
        -S) STATIC_STORE="$2"; shift 2 ;;
        -P) PROJECT="$2"; shift 2 ;;
        -U) RUN_USER="$2"; shift 2 ;;
        -o) OVERWRITE="true"; shift ;;
        -k) SKIP_PROCESSING="true"; shift ;;
        -n) DRY_RUN="true"; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

if [[ -z "$RUN_NAME" ]]; then
    echo "Error: -s RUN_NAME is required" >&2
    usage
    exit 1
fi

AFIM_OUTPUT_ROOT="${AFIM_OUTPUT_ROOT:-/g/data/${PROJECT}/${RUN_USER}/afim_output}"
HISTORY_ROOT="${HISTORY_ROOT:-/g/data/${PROJECT}/${RUN_USER}/cice-dirs/runs/${RUN_NAME}/history}"
REFERENCE_ROOT="${REFERENCE_ROOT:-${AFIM_OUTPUT_ROOT}/${REFERENCE_SIM}}"
STATIC_STORE="${STATIC_STORE:-${AFIM_OUTPUT_ROOT}/CICE_0p25_Cgrid_coords.zarr}"

PBS_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/run_health_check.pbs"
QSUB_VARS="RUN_NAME=${RUN_NAME},REFERENCE_SIM=${REFERENCE_SIM},PROJECT=${PROJECT},RUN_USER=${RUN_USER},AFIM_OUTPUT_ROOT=${AFIM_OUTPUT_ROOT},HISTORY_ROOT=${HISTORY_ROOT},REFERENCE_ROOT=${REFERENCE_ROOT},STATIC_STORE=${STATIC_STORE}"
[[ -n "$START_DATE" ]] && QSUB_VARS+=",START_DATE=${START_DATE}"
[[ -n "$END_DATE" ]] && QSUB_VARS+=",END_DATE=${END_DATE}"
if [[ "$OVERWRITE" == "true" ]]; then
    QSUB_VARS+=",OVERWRITE_CANDIDATE_HISTORY=true,OVERWRITE_CANDIDATE_CLASSIFICATION=true,OVERWRITE_CANDIDATE_METRICS=true"
fi
[[ "$SKIP_PROCESSING" == "true" ]] && QSUB_VARS+=",SKIP_CANDIDATE_PROCESSING=true"

JOB_NAME="${RUN_NAME}_health"
if [[ "$DRY_RUN" == "true" ]]; then
    echo "[DRY_RUN] qsub -N ${JOB_NAME} -v ${QSUB_VARS} ${PBS_SCRIPT}"
    exit 0
fi

qsub -N "$JOB_NAME" -v "$QSUB_VARS" "$PBS_SCRIPT"
