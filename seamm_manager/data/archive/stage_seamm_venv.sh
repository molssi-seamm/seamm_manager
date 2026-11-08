# Put the SEAMM environment on node-local disk on every node of this Slurm job.
#
# For a queue section's setup (sourced, before SEAMM starts):
#     setup = source @ROOT@/bin/stage_seamm_venv.sh
# with remote_run_from_jobserver = @ROOT@/bin/run_from_jobserver.
#
# It unpacks the archive @ROOT@/env-archives/seamm-venv.tar links to
# (seamm-venv-<version>.tar, published by seamm-manager with
# seamm-environment-storage = archive) into $TMPDIR/seamm-venv -- the same path on
# every node, since MPI ranks there may need it -- then sets SEAMM_VENV and puts its
# bin first on PATH. The link is read once, so a job keeps the version it started
# with even if an update switches the link meanwhile.
#
# No fallback (Paul 2026-11-07): if the archive exists but cannot be staged, the job
# FAILS with a message rather than running on the shared environment. Only when there
# is no archive does the job use the shared environment, @ROOT@/venv.
# It reports on the job's stdout/stderr only (no shared log file, whose appends from
# many jobs contend), so failures are counted from the jobs' outputs.
#
# Not for sections with tasks = queue: their task bundles are separate jobs, which
# start the evaluator's Python by its path, and this path is only in this job.
# SEAMM_VENV_ARCHIVE overrides the archive (for tests).
#
# Installed by seamm-manager (seamm_manager/data/archive/stage_seamm_venv.sh).
_stage_seamm_venv() {
    local root=@ROOT@
    local archive
    archive=$(readlink -f "${SEAMM_VENV_ARCHIVE:-$root/env-archives/seamm-venv.tar}" 2>/dev/null)
    local dest=${TMPDIR:-/tmp}/seamm-venv
    local nodes=${SLURM_JOB_NUM_NODES:-1}
    local t0=$SECONDS
    _fail() {
        echo "stage_seamm_venv: FAILED to stage $archive on $nodes node(s): $*" >&2
        return 1
    }
    if [ -z "$archive" ] || [ ! -e "$archive" ]; then
        echo "stage_seamm_venv: no archive; using the shared environment $(readlink -f "$root/venv")"
        return 0
    fi
    local err
    if [ "$nodes" -gt 1 ]; then
        # One read of the archive from the shared file system; Slurm copies it to the nodes.
        err=$(sbcast --force "$archive" "$dest.tar" 2>&1) || { _fail "sbcast: ${err:0:300}"; return 1; }
        err=$(srun --export=ALL --nodes="$nodes" --ntasks="$nodes" --ntasks-per-node=1 \
               --cpus-per-task=1 --mem=0 --overlap /bin/bash -c \
               "mkdir -p '$dest' && tar -C '$dest' --strip-components=1 -xf '$dest.tar' && rm -f '$dest.tar'" 2>&1) \
            || { _fail "srun untar: ${err:0:300}"; return 1; }
    else
        err=$(mkdir -p "$dest" 2>&1 && tar -C "$dest" --strip-components=1 -xf "$archive" 2>&1) \
            || { _fail "untar: ${err:0:300}"; return 1; }
    fi
    err=$("$dest/bin/python" -c "import seamm" 2>&1) || { _fail "import seamm: ${err:0:300}"; return 1; }
    export SEAMM_VENV=$dest
    export PATH="$dest/bin:$PATH"
    echo "stage_seamm_venv: $(basename "$archive") -> $dest on $nodes node(s) in $((SECONDS - t0)) s"
}
if ! _stage_seamm_venv; then
    unset -f _stage_seamm_venv _fail
    exit 1
fi
unset -f _stage_seamm_venv _fail
