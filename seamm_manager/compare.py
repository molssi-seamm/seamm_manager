# -*- coding: utf-8 -*-

"""The 'compare' command: run one flowchart in two environments and diff the
results.

The comparison harness of the parallel-execution campaign (phase 0). Each side
is an installation root, an environment directory, or a version of this
installation's environment (``venvs/<stamp>``); the flowchart runs with each
side's ``run_flowchart`` in its own working directory, with the same arguments,
and the two trees are compared file by file:

- ``.json``: parsed, compared with a numeric tolerance; keys whose names say
  they are volatile (times, dates, versions, hosts, paths) are ignored;
- ``.csv``: cell by cell, numbers with tolerance;
- structure and data files (``.xyz``, ``.extxyz``, ``.sdf``, ``.mmcif``, ``.cif``,
  ``.pdb``, ``.dat``): token by token, numbers with tolerance;
- text (``.out``, ``.txt``, ``.log``, ``.inp``, ...): line by line after
  normalizing timestamps, durations, versions and the working directories;
- anything else: size only.

Files present on one side only are reported. The exit status is 0 when every
file agrees within tolerance.
"""

import csv
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from . import my

JSON_SUFFIXES = {".json"}
CSV_SUFFIXES = {".csv"}
NUMERIC_TEXT_SUFFIXES = {
    ".xyz",
    ".extxyz",
    ".sdf",
    ".mol",
    ".mmcif",
    ".cif",
    ".pdb",
    ".dat",
}
TEXT_SUFFIXES = {
    ".out",
    ".txt",
    ".log",
    ".inp",
    ".in",
    ".yaml",
    ".yml",
    ".flow",
    ".rst",
    ".md",
    ".sh",
}

# Keys in JSON whose values are expected to differ between runs
VOLATILE_KEY_PARTS = (
    "time",
    "date",
    "version",
    "host",
    "path",
    "directory",
    "pid",
    "root",
    "uuid",
)

# Lines or parts of text lines that are expected to differ between runs
VOLATILE_LINE_PATTERNS = [
    re.compile(r"\b\d{4}[./-]\d{2}[./-]\d{2}\b"),  # dates
    re.compile(r"\b\d{1,2}:\d{2}:\d{2}(\.\d+)?\b"),  # times and durations
    # "Elapsed time: ...", "WALL-CLOCK TIME = ...", "CPU_TIME:SEC=...",
    # "TOTAL JOB TIME:" (not \b: an underscore, as in CPU_TIME, is a word character)
    re.compile(r"(?<![a-z])time(?![a-z])\s*(\[\d+\])?\s*[:=]", re.I),
    re.compile(r"\b(Process|Elapsed|Wall|CPU|Total|Computation)\s+time\b", re.I),
    re.compile(r"\bversion\b", re.I),
    re.compile(r"\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b"),
    re.compile(r"\b\d+(\.\d+)?\s*(s|sec|seconds|ms|min|minutes|h|hours)\b"),
    re.compile(r"\b(hostname|host name|running on|job id|pid)\b", re.I),
]

NUMBER = re.compile(r"^[-+]?(\d+\.?\d*|\.\d+)([eEdD][-+]?\d+)?$")


def setup(parser):
    """Define the command-line interface for the comparison."""
    subparser = parser.add_parser(
        "compare",
        help=(
            "Run a flowchart in two environments and compare the results, e.g. "
            "the current environment and a newly built version before switching."
        ),
    )
    subparser.set_defaults(func=compare)
    subparser.add_argument("flowchart", help="The flowchart (.flow) to run.")
    subparser.add_argument(
        "-a",
        default="current",
        help=(
            "The first environment: 'current' (this installation's), a version of "
            "it (e.g. 2026-10-02T14-21-58 or 'previous'), an environment "
            "directory, or another installation's root. Default %(default)s."
        ),
    )
    subparser.add_argument(
        "-b",
        default="newest",
        help=(
            "The second environment, likewise; 'newest' is the newest version of "
            "this installation's environment. Default %(default)s."
        ),
    )
    subparser.add_argument(
        "--work",
        default=None,
        help="Where to run (subdirectories a/ and b/). Default: a temporary directory.",
    )
    subparser.add_argument(
        "--keep", action="store_true", help="Keep the working directories afterwards."
    )
    subparser.add_argument(
        "--rtol",
        type=float,
        default=1.0e-6,
        help="Relative tolerance, default %(default)s.",
    )
    subparser.add_argument(
        "--atol",
        type=float,
        default=1.0e-9,
        help="Absolute tolerance, default %(default)s.",
    )
    subparser.add_argument(
        "--no-run",
        action="store_true",
        help="Only compare existing a/ and b/ under --work; do not run the flowchart.",
    )
    subparser.add_argument(
        "args", nargs="*", help="Arguments for the flowchart, after '--'."
    )


# ---- environments ------------------------------------------------------------


def resolve_environment(spec):
    """The environment directory and installation root for a side's spec.

    Returns
    -------
    (pathlib.Path, pathlib.Path)
        The environment (holding ``bin/run_flowchart``) and the root it belongs to.
    """
    uv = my.uv
    if spec == "current":
        return uv.real_path, uv.root
    versions = uv.versions()
    names = [name for name, _ in versions]
    if spec == "newest":
        if not versions:
            raise ValueError("This installation's environment has no versions yet.")
        return versions[-1][1], uv.root
    if spec == "previous":
        current = uv.current_version
        older = [path for name, path in versions if current is None or name < current]
        if not older:
            raise ValueError("There is no previous version of the environment.")
        return older[-1], uv.root
    if spec in names:
        return dict(versions)[spec], uv.root
    path = Path(spec).expanduser()
    if (path / "bin" / "run_flowchart").exists():
        root = path.parent.parent if path.parent.name == "venvs" else path.parent
        return path.resolve(), root
    if (path / "venv").exists():
        env = (path / "venv").resolve()
        return env, path
    raise ValueError(
        f"'{spec}' is not 'current', 'newest', 'previous', a version "
        f"({', '.join(names) or 'none'}), an environment or an installation root."
    )


def run_flowchart(environment, root, flowchart, directory, args):
    """Run `flowchart` with `environment`'s run_flowchart in `directory`."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    exe = Path(environment) / "bin" / "run_flowchart"
    command = [str(exe), str(Path(flowchart).resolve()), "--root", str(root), *args]
    with open(directory / "harness_run.log", "w") as log:
        log.write(" ".join(command) + "\n\n")
        log.flush()
        result = subprocess.run(
            command,
            cwd=directory,
            stdout=log,
            stderr=subprocess.STDOUT,
            env={**os.environ, "SEAMM_ROOT": str(root)},
        )
    return result.returncode


# ---- comparison ---------------------------------------------------------------


def _is_number(text):
    return bool(NUMBER.match(text.strip())) if isinstance(text, str) else False


def _to_float(text):
    return float(text.strip().replace("D", "e").replace("d", "e"))


def _close(a, b, rtol, atol):
    if math.isnan(a) and math.isnan(b):
        return True
    return math.isclose(a, b, rel_tol=rtol, abs_tol=atol)


def _volatile_key(key):
    k = str(key).lower()
    return any(part in k for part in VOLATILE_KEY_PARTS)


def compare_json(a, b, rtol, atol, path=""):
    """Differences between two parsed JSON values, as ['where: what', ...]."""
    diffs = []
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if _volatile_key(key):
                continue
            where = f"{path}/{key}"
            if key not in a:
                diffs.append(f"{where}: only in b")
            elif key not in b:
                diffs.append(f"{where}: only in a")
            else:
                diffs.extend(compare_json(a[key], b[key], rtol, atol, where))
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            diffs.append(f"{path}: {len(a)} vs {len(b)} items")
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs.extend(compare_json(x, y, rtol, atol, f"{path}[{i}]"))
    elif isinstance(a, bool) or isinstance(b, bool):
        # True == 1 in Python; a boolean must stay a boolean
        if type(a) is not type(b) or a != b:
            diffs.append(f"{path}: {a!r} vs {b!r}")
    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):
        if not _close(float(a), float(b), rtol, atol):
            diffs.append(f"{path}: {a!r} vs {b!r}")
    elif isinstance(a, str) and isinstance(b, str) and _is_number(a) and _is_number(b):
        if not _close(_to_float(a), _to_float(b), rtol, atol):
            diffs.append(f"{path}: {a!r} vs {b!r}")
    elif a != b:
        diffs.append(f"{path}: {a!r} vs {b!r}")
    return diffs


def compare_csv(text_a, text_b, rtol, atol):
    """Differences between two CSV texts."""
    rows_a = list(csv.reader(text_a.splitlines()))
    rows_b = list(csv.reader(text_b.splitlines()))
    if len(rows_a) != len(rows_b):
        return [f"{len(rows_a)} vs {len(rows_b)} rows"]
    diffs = []
    for i, (ra, rb) in enumerate(zip(rows_a, rows_b)):
        if len(ra) != len(rb):
            diffs.append(f"row {i}: {len(ra)} vs {len(rb)} columns")
            continue
        for j, (x, y) in enumerate(zip(ra, rb)):
            if _is_number(x) and _is_number(y):
                if not _close(_to_float(x), _to_float(y), rtol, atol):
                    diffs.append(f"row {i} col {j}: {x} vs {y}")
            elif x != y:
                diffs.append(f"row {i} col {j}: {x!r} vs {y!r}")
    return diffs


def compare_numeric_text(text_a, text_b, rtol, atol):
    """Differences between two texts compared token by token, numbers with
    tolerance (structure files)."""
    lines_a, lines_b = text_a.splitlines(), text_b.splitlines()
    if len(lines_a) != len(lines_b):
        return [f"{len(lines_a)} vs {len(lines_b)} lines"]
    diffs = []
    for i, (la, lb) in enumerate(zip(lines_a, lines_b)):
        ta, tb = la.split(), lb.split()
        if len(ta) != len(tb):
            diffs.append(f"line {i + 1}: {la!r} vs {lb!r}")
            continue
        for x, y in zip(ta, tb):
            if _is_number(x) and _is_number(y):
                if not _close(_to_float(x), _to_float(y), rtol, atol):
                    diffs.append(f"line {i + 1}: {x} vs {y}")
                    break
            elif x != y:
                diffs.append(f"line {i + 1}: {x!r} vs {y!r}")
                break
    return diffs


def normalize_text(text, replacements=()):
    """The lines of `text` that are not expected to vary between runs, with the
    given (old, new) replacements applied first (the working directories)."""
    for old, new in replacements:
        text = text.replace(old, new)
    kept = []
    for line in text.splitlines():
        if any(p.search(line) for p in VOLATILE_LINE_PATTERNS):
            continue
        kept.append(line.rstrip())
    return kept


def compare_text(text_a, text_b, replacements=()):
    """Differences between two texts after normalization, as a few diff lines."""
    import difflib

    a = normalize_text(text_a, replacements)
    b = normalize_text(text_b, replacements)
    if a == b:
        return []
    diff = [
        line
        for line in difflib.unified_diff(a, b, lineterm="", n=0)
        if not line.startswith(("---", "+++", "@@"))
    ]
    return diff


def compare_trees(
    dir_a,
    dir_b,
    rtol=1.0e-6,
    atol=1.0e-9,
    ignore=("harness_run.log",),
    replacements=(),
):
    """Compare two result trees.

    `replacements` are further (old, new) text substitutions made before
    comparing text and JSON, e.g. the two installations' roots.

    Returns
    -------
    [(relative path, status, details)]
        status is one of 'identical', 'within tolerance', 'different', 'only in a',
        'only in b', 'not compared'.
    """
    dir_a, dir_b = Path(dir_a), Path(dir_b)
    files_a = {p.relative_to(dir_a) for p in dir_a.rglob("*") if p.is_file()}
    files_b = {p.relative_to(dir_b) for p in dir_b.rglob("*") if p.is_file()}
    # Longest first, so that ~/SEAMM does not eat the front of ~/SEAMM_DEV
    replacements = sorted(
        (
            (str(dir_a.resolve()), "<WORK>"),
            (str(dir_b.resolve()), "<WORK>"),
            *replacements,
        ),
        key=lambda item: -len(item[0]),
    )
    results = []
    for rel in sorted(files_a | files_b, key=str):
        if rel.name in ignore:
            continue
        if rel not in files_b:
            results.append((rel, "only in a", []))
            continue
        if rel not in files_a:
            results.append((rel, "only in b", []))
            continue
        pa, pb = dir_a / rel, dir_b / rel
        suffix = rel.suffix.lower()
        try:
            if suffix in JSON_SUFFIXES:
                a, b = _load_json(pa, replacements), _load_json(pb, replacements)
                diffs = compare_json(a, b, rtol, atol)
                status = _status(diffs, pa.read_bytes() == pb.read_bytes())
            elif suffix in CSV_SUFFIXES:
                diffs = compare_csv(pa.read_text(), pb.read_text(), rtol, atol)
                status = _status(diffs, pa.read_bytes() == pb.read_bytes())
            elif suffix in NUMERIC_TEXT_SUFFIXES:
                diffs = compare_numeric_text(pa.read_text(), pb.read_text(), rtol, atol)
                status = _status(diffs, pa.read_bytes() == pb.read_bytes())
            elif suffix in TEXT_SUFFIXES or _looks_like_text(pa):
                diffs = compare_text(
                    pa.read_text(errors="replace"),
                    pb.read_text(errors="replace"),
                    replacements,
                )
                status = _status(diffs, pa.read_bytes() == pb.read_bytes())
            else:
                sa, sb = pa.stat().st_size, pb.stat().st_size
                diffs = [] if sa == sb else [f"{sa} vs {sb} bytes"]
                status = "not compared" if sa == sb else "different"
        except (UnicodeDecodeError, json.JSONDecodeError, OSError) as e:
            diffs = [f"could not compare: {e}"]
            status = "different"
        results.append((rel, status, diffs))
    return results


def _load_json(path, replacements=()):
    """Parse a JSON file, skipping a SEAMM header line such as
    ``!MolSSI job_data 1.0`` and applying the text `replacements` (paths)."""
    text = path.read_text()
    if text.startswith("!"):
        text = text.split("\n", 1)[1] if "\n" in text else ""
    for old, new in replacements:
        text = text.replace(old, new)
    return json.loads(text)


def _status(diffs, identical):
    if diffs:
        return "different"
    return "identical" if identical else "within tolerance"


def _looks_like_text(path, sample=4096):
    try:
        data = path.read_bytes()[:sample]
    except OSError:
        return False
    if b"\0" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def report(results, max_details=5):
    """Print the comparison and return True if everything agrees."""
    from tabulate import tabulate

    counts = {}
    rows = []
    for rel, status, diffs in results:
        counts[status] = counts.get(status, 0) + 1
        if status in ("identical", "within tolerance", "not compared"):
            continue
        detail = "; ".join(diffs[:max_details])
        if len(diffs) > max_details:
            detail += f"; ... {len(diffs) - max_details} more"
        rows.append((str(rel), status, detail[:200]))
    if rows:
        print(tabulate(rows, ("File", "Status", "Details"), tablefmt="simple"))
        print()
    summary = ", ".join(f"{n} {status}" for status, n in sorted(counts.items()))
    print(f"Compared {len(results)} files: {summary or 'none'}.")
    return not any(s in ("different", "only in a", "only in b") for _, s, _ in results)


# ---- the command ---------------------------------------------------------------


def compare():
    options = my.options
    flowchart = Path(options.flowchart).expanduser()
    if not flowchart.exists():
        print(f"The flowchart {flowchart} does not exist.")
        return 1
    try:
        env_a, root_a = resolve_environment(options.a)
        env_b, root_b = resolve_environment(options.b)
    except ValueError as e:
        print(e)
        return 1
    if env_a == env_b:
        print(f"Both sides are the same environment, {env_a}.")
        return 1

    work = (
        Path(options.work).expanduser()
        if options.work
        else Path(tempfile.mkdtemp(prefix="seamm-compare-"))
    )
    work.mkdir(parents=True, exist_ok=True)
    dir_a, dir_b = work / "a", work / "b"
    print(f"a: {env_a} (root {root_a})")
    print(f"b: {env_b} (root {root_b})")
    print(f"working in {work}")

    if not options.no_run:
        for label, env, root, directory in (
            ("a", env_a, root_a, dir_a),
            ("b", env_b, root_b, dir_b),
        ):
            if directory.exists():
                shutil.rmtree(directory)
            print(f"running {label} ...", end=" ", flush=True)
            code = run_flowchart(env, root, flowchart, directory, options.args)
            print(
                "ok"
                if code == 0
                else f"exit {code} (see {directory / 'harness_run.log'})"
            )

    roots = ()
    if root_a != root_b:
        roots = ((str(root_a), "<ROOT>"), (str(root_b), "<ROOT>"))
    results = compare_trees(
        dir_a, dir_b, rtol=options.rtol, atol=options.atol, replacements=roots
    )
    ok = report(results)
    if not options.keep and not options.work:
        shutil.rmtree(work, ignore_errors=True)
    elif options.keep or options.work:
        print(f"The runs are kept in {work}")
    return 0 if ok else 1
