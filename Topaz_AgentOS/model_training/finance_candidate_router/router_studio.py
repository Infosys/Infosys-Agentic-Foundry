"""Router Studio — an interactive TUI to turn any open-source model into a
Jev-style calibrated candidate-logit router.

It orchestrates the existing pipeline end to end and reuses every program:

  - mlx_lm.convert ............ optional: convert a HF model to local MLX 4-bit
  - build_direct_dataset ...... build the direct 50-choice dataset
  - train_mlx audit ........... CPU-only prompt/token audit
  - train_mlx train ........... smoke and full LoRA training
  - train_mlx evaluate ........ score a trained adapter on a split
  - eval_jev_direct ........... compare against the Jev (System One) API

Nothing about the pipeline is duplicated here; this is a thin, menu-driven
orchestrator over the package's existing entry points. It runs in a normal
macOS Terminal (MLX training needs Metal).

Run from the repo root:

    python3 -m model_training.finance_candidate_router.router_studio
"""

from __future__ import annotations

import json
import math
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable or "python3"
PACKAGE = "model_training.finance_candidate_router"

# A base model is a local directory or a Hugging Face repo id; allow only the
# characters those use, and never a leading "-" (it would be read as an option).
_MODEL_REF_RE = re.compile(r"[\w.@+()~:/\-]{1,1024}")


def _model_ref_from_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        return ""
    if value.startswith("-") or not _MODEL_REF_RE.fullmatch(value):
        print(f"Ignoring invalid {name}; set the base model from the menu instead.", file=sys.stderr)
        return ""
    return "".join(value)
CONFIG_PATH = REPO_ROOT / "model_training/finance_candidate_router/.router_studio_config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    # No portable default: set ROUTER_STUDIO_BASE_MODEL or use menu option 1.
    "base_model": _model_ref_from_env("ROUTER_STUDIO_BASE_MODEL"),
    "data_dir": "enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1",
    "routing_mode": "direct",
    "adapter_dir": "adapters/router_studio_run_v1",
    "seed": 17,
    "max_length": 4096,
    "num_layers": 8,
    "rank": 16,
    "scale": 2.0,
    "dropout": 0.05,
    "learning_rate": 2e-5,
    "gradient_accumulation": 8,
    "epochs_full": 3,
    "smoke_iters": 20,
    "jev_model": "jev-latest",
}

DIRECT_DATA = "enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1"
HIERARCHICAL_DATA = "enterprise_root/tenants/company/training_data/finance_router_candidate_v1"

# Hyperparameters the "Configure hyperparameters" screen exposes, with types.
TUNABLES: list[tuple[str, type]] = [
    ("seed", int),
    ("max_length", int),
    ("num_layers", int),
    ("rank", int),
    ("scale", float),
    ("dropout", float),
    ("learning_rate", float),
    ("gradient_accumulation", int),
    ("epochs_full", int),
    ("smoke_iters", int),
]


def ask(prompt: str, default: str | None = None) -> str:
    suffix = f" [{default}]" if default is not None else ""
    try:
        value = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        return default or ""
    return value or (default or "")


def pause() -> None:
    try:
        input("\nPress Enter to continue...")
    except EOFError:
        pass


def run(cmd: list[str], *, log: Path | None = None, caffeinate: bool = False) -> int:
    """Run a command from the repo root, streaming output live (optionally tee'd)."""
    if caffeinate and sys.platform == "darwin":
        cmd = ["caffeinate", "-i", *cmd]
    printable = shlex.join(cmd)
    print(f"\n$ {printable}\n", flush=True)
    if log is not None:
        # Tee in Python (no shell): stream merged stdout/stderr live and to the log.
        log.parent.mkdir(parents=True, exist_ok=True)
        with open(log, "w", encoding="utf-8", errors="replace") as log_file:
            proc = subprocess.Popen(
                cmd, cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
            )
            assert proc.stdout is not None
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
            return proc.wait()
    return subprocess.run(cmd, cwd=REPO_ROOT).returncode


def load_config() -> dict[str, Any]:
    config = dict(DEFAULT_CONFIG)
    if CONFIG_PATH.exists():
        try:
            config.update(json.loads(CONFIG_PATH.read_text()))
        except (json.JSONDecodeError, OSError):
            print(f"(could not read {CONFIG_PATH}; using defaults)")
    return config


def save_config(config: dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2) + "\n")
    print(f"Saved config to {CONFIG_PATH}")


def data_dir_path(config: dict[str, Any]) -> Path:
    path = Path(config["data_dir"])
    return path if path.is_absolute() else REPO_ROOT / path


def adapter_path(config: dict[str, Any]) -> Path:
    path = Path(config["adapter_dir"])
    return path if path.is_absolute() else REPO_ROOT / path


def dataset_train_count(config: dict[str, Any]) -> int | None:
    data_dir = data_dir_path(config)
    manifest = data_dir / "manifest.json"
    if manifest.exists():
        try:
            return json.loads(manifest.read_text())["splits"]["train"]["records"]
        except (KeyError, json.JSONDecodeError, OSError):
            pass
    train = data_dir / "train.jsonl"
    if train.exists():
        return sum(1 for line in train.open() if line.strip())
    return None


def full_iters(config: dict[str, Any]) -> int | None:
    """Compute full-run iterations as epochs x train_count, rounded up to a
    multiple of the gradient-accumulation count so the last group is applied."""
    count = dataset_train_count(config)
    if not count:
        return None
    accum = max(1, int(config["gradient_accumulation"]))
    target = count * int(config["epochs_full"])
    return math.ceil(target / accum) * accum


def adapter_ready(config: dict[str, Any]) -> bool:
    return (adapter_path(config) / "adapter_config.json").exists()


def action_set_model(config: dict[str, Any]) -> None:
    print("\nSet the base model (local MLX directory or a Hugging Face repo id).")
    print("Non-MLX HF models can be converted first with menu option 2.")
    config["base_model"] = ask("Base model path or HF id", config["base_model"])


def action_convert_hf(config: dict[str, Any]) -> None:
    print("\nConvert a Hugging Face model to a local MLX 4-bit model.")
    hf_id = ask("HF repo id (e.g. Qwen/Qwen2.5-1.5B-Instruct)")
    if not hf_id:
        print("Cancelled.")
        return
    out = ask("Output MLX dir", str(REPO_ROOT / f"models/{hf_id.split('/')[-1]}-4bit"))
    code = run([PYTHON, "-m", "mlx_lm.convert", "--hf-path", hf_id, "-q", "--mlx-path", out])
    if code == 0:
        config["base_model"] = out
        print(f"Converted. Base model set to {out}")


def action_dataset(config: dict[str, Any]) -> None:
    direct = config["routing_mode"] == "direct"
    builder = "build_direct_dataset" if direct else "build_dataset"
    default_out = DIRECT_DATA if direct else HIERARCHICAL_DATA
    print(f"\nDataset options (routing mode: {config['routing_mode']}):")
    print("  1) Point to an existing dataset directory")
    print(f"  2) Build/rebuild the dataset ({builder})")
    choice = ask("Choose", "1")
    if choice == "1":
        config["data_dir"] = ask("Dataset directory", config["data_dir"])
    elif choice == "2":
        source = ask("Source dir (blank = builder default)", "")
        output = ask("Output dir", default_out)
        cmd = [PYTHON, "-m", f"{PACKAGE}.{builder}", "--output-dir", output]
        if source:
            cmd += ["--source-dir", source]
        if run(cmd) == 0:
            config["data_dir"] = output
    count = dataset_train_count(config)
    if count:
        print(f"Dataset train records: {count}")


def action_hyperparams(config: dict[str, Any]) -> None:
    print("\nConfigure hyperparameters (Enter keeps the current value).")
    for key, caster in TUNABLES:
        raw = ask(f"  {key}", str(config[key]))
        try:
            config[key] = caster(raw)
        except ValueError:
            print(f"    (invalid {key!r}; kept {config[key]})")
    config["adapter_dir"] = ask("Adapter output dir", config["adapter_dir"])
    iters = full_iters(config)
    if iters:
        print(f"Full run will use {iters} iters "
              f"({config['epochs_full']} epochs x {dataset_train_count(config)} records, "
              f"rounded to a multiple of {config['gradient_accumulation']}).")


def _train_common(config: dict[str, Any]) -> list[str]:
    return [
        PYTHON, "-u", "-m", f"{PACKAGE}.train_mlx", "train",
        "--routing-mode", config["routing_mode"],
        "--model", config["base_model"],
        "--data-dir", config["data_dir"],
        "--seed", str(config["seed"]),
        "--max-length", str(config["max_length"]),
        "--learning-rate", str(config["learning_rate"]),
        "--num-layers", str(config["num_layers"]),
        "--rank", str(config["rank"]),
        "--scale", str(config["scale"]),
        "--dropout", str(config["dropout"]),
    ]


def _require_model(config: dict[str, Any]) -> bool:
    if not str(config.get("base_model", "")).strip():
        print(
            "No base model set. Use menu option 1 (Set base model) or set the "
            "ROUTER_STUDIO_BASE_MODEL environment variable first."
        )
        return False
    return True


def _guard_adapter(path: Path) -> bool:
    if path.exists() and any(path.iterdir()):
        print(f"Adapter dir '{path}' exists and is not empty.")
        if ask("Reuse it anyway? (y/N)", "N").lower() != "y":
            print("Cancelled — set a fresh adapter dir in option 4.")
            return False
    return True


def action_audit(config: dict[str, Any]) -> None:
    if not _require_model(config):
        return
    print("\nCPU-only token audit (verifies prompts fit --max-length for this model's tokenizer).")
    cmd = [
        PYTHON, "-m", f"{PACKAGE}.train_mlx", "audit",
        "--routing-mode", config["routing_mode"],
        "--model", config["base_model"],
        "--data-dir", config["data_dir"],
        "--seed", str(config["seed"]),
        "--max-length", str(config["max_length"]),
    ]
    run(cmd)


def action_smoke(config: dict[str, Any]) -> None:
    if not _require_model(config):
        return
    path = adapter_path(config).with_name(adapter_path(config).name + "_smoke")
    if not _guard_adapter(path):
        return
    accum = 4
    cmd = _train_common(config) + [
        "--adapter-path", str(path),
        "--iters", str(config["smoke_iters"]),
        "--gradient-accumulation", str(accum),
        "--steps-per-report", "5",
        "--steps-per-eval", "10",
        "--save-every", "10",
        "--early-stopping-patience", "3",
        "--min-delta", "1e-4",
    ]
    log = REPO_ROOT / f"artifacts/{path.name}.log"
    run(cmd, log=log, caffeinate=True)


def action_full(config: dict[str, Any]) -> None:
    if not _require_model(config):
        return
    iters = full_iters(config)
    if not iters:
        print("Cannot determine dataset size; build/point to a dataset first.")
        return
    path = adapter_path(config)
    if not _guard_adapter(path):
        return
    eval_every = max(config["gradient_accumulation"], (iters // 4 // config["gradient_accumulation"]) * config["gradient_accumulation"] or config["gradient_accumulation"])
    cmd = _train_common(config) + [
        "--adapter-path", str(path),
        "--iters", str(iters),
        "--gradient-accumulation", str(config["gradient_accumulation"]),
        "--steps-per-report", str(max(config["gradient_accumulation"], eval_every // 2)),
        "--steps-per-eval", str(eval_every),
        "--save-every", str(eval_every),
        "--early-stopping-patience", "2",
        "--min-delta", "1e-4",
    ]
    log = REPO_ROOT / f"artifacts/{path.name}.log"
    run(cmd, log=log, caffeinate=True)


def action_evaluate(config: dict[str, Any]) -> None:
    if not _require_model(config):
        return
    if not adapter_ready(config):
        print(f"No trained adapter at {adapter_path(config)} — train first.")
        return
    cmd = [
        PYTHON, "-m", f"{PACKAGE}.train_mlx", "evaluate",
        "--data-dir", config["data_dir"],
        "--adapter-path", str(adapter_path(config)),
        "--model", config["base_model"],
        "--split", "valid",
    ]
    run(cmd)


def jev_report_path(config: dict[str, Any]) -> Path:
    return REPO_ROOT / f"artifacts/jev_{adapter_path(config).name}.json"


def action_compare_jev(config: dict[str, Any]) -> None:
    if config["routing_mode"] != "direct":
        print("The Jev comparison harness is direct-only; switch to direct mode (option 3).")
        return
    print("\nCompare against the Jev API on the validation split (makes paid API calls).")
    limit = ask("Limit records (blank = all)", "")
    out = jev_report_path(config)
    cmd = [
        PYTHON, "-m", f"{PACKAGE}.eval_jev_direct",
        "--data-dir", config["data_dir"],
        "--split", "valid",
        "--model", config["jev_model"],
        "--out", str(out),
    ]
    if limit:
        cmd += ["--limit", limit]
    run(cmd)


def _read_metrics(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def action_show_results(config: dict[str, Any]) -> None:
    local = _read_metrics(adapter_path(config) / "valid_evaluation.json") \
        or _read_metrics(adapter_path(config) / "after_validation.json")
    jev = _read_metrics(jev_report_path(config))
    if not local and not jev:
        print("No results yet. Run evaluate (8) and/or compare (9) first.")
        return

    def fmt(report: dict[str, Any] | None, key: str, pct: bool = False) -> str:
        if not report or key not in report or report[key] is None:
            return "   -"
        value = report[key]
        return f"{100 * value:6.2f}%" if pct else f"{value:7.4f}"

    print("\n=== Results: your model vs Jev ===")
    print(f"{'metric':<26}{'your model':>14}{'jev':>14}")
    print(f"{'accuracy':<26}{fmt(local, 'accuracy', True):>14}{fmt(jev, 'accuracy', True):>14}")
    print(f"{'mean_nll':<26}{fmt(local, 'mean_nll'):>14}{fmt(jev, 'mean_nll'):>14}")
    print(f"{'mean_brier':<26}{fmt(local, 'mean_brier'):>14}{fmt(jev, 'mean_brier'):>14}")
    print(f"{'ECE':<26}{fmt(local, 'expected_calibration_error'):>14}{fmt(jev, 'expected_calibration_error'):>14}")

    print("\ncoverage @ confidence (share auto-routed @ accuracy on them):")
    for threshold in ("0.7", "0.8", "0.9"):
        left = (local or {}).get("coverage_at_confidence", {}).get(threshold)
        right = (jev or {}).get("coverage_at_confidence", {}).get(threshold)

        def cell(cov: dict[str, Any] | None) -> str:
            if not cov:
                return "   -"
            acc = f"{100 * cov['accuracy']:.0f}%" if cov.get("accuracy") is not None else "n/a"
            return f"{100 * cov['coverage']:.0f}% @ {acc}"

        print(f"{'  >= ' + threshold:<26}{cell(left):>14}{cell(right):>14}")


def action_save(config: dict[str, Any]) -> None:
    save_config(config)


def action_load(config: dict[str, Any]) -> None:
    loaded = load_config()
    config.clear()
    config.update(loaded)
    print("Config reloaded.")


def action_set_routing_mode(config: dict[str, Any]) -> None:
    print("\nRouting mode:")
    print("  direct       - one 50-way decision (skills + no-match); Jev-comparable")
    print("  hierarchical - domain then skill (two decisions)")
    mode = ask("Mode (direct|hierarchical)", config["routing_mode"]).strip().lower()
    if mode not in ("direct", "hierarchical"):
        print("Unchanged.")
        return
    config["routing_mode"] = mode
    suggested = DIRECT_DATA if mode == "direct" else HIERARCHICAL_DATA
    if ask(f"Switch dataset to the {mode} default ({suggested})? (Y/n)", "Y").lower() != "n":
        config["data_dir"] = suggested


def action_distill(config: dict[str, Any]) -> None:
    if config["routing_mode"] != "direct":
        print("Distillation uses the direct Jev harness; switch to direct mode (option 3) first.")
        return
    print("\nDistill from Jev: label the TRAIN split with Jev (teacher), keeping")
    print("valid/test as ground truth. Produces a Jev-relabeled dataset (hard labels")
    print("where Jev is confident) with teacher probabilities stored for future")
    print("soft-target training. Makes paid Jev API calls over the train set.")
    out = ask("Distilled dataset out-dir", str(data_dir_path(config)) + "_distilled")
    threshold = ask("Accept Jev label when confidence >=", "0.6")
    limit = ask("Limit records (blank = all)", "")
    cmd = [
        PYTHON, "-m", f"{PACKAGE}.distill_jev",
        "--data-dir", config["data_dir"],
        "--out-dir", out,
        "--model", config["jev_model"],
        "--confidence", threshold,
    ]
    if limit:
        cmd += ["--limit", limit]
    if run(cmd) == 0 and ask("Set the distilled dataset as active? (Y/n)", "Y").lower() != "n":
        config["data_dir"] = out


MENU = [
    ("Set base model", action_set_model),
    ("Convert HF model -> MLX 4-bit", action_convert_hf),
    ("Set routing mode (direct|hierarchical)", action_set_routing_mode),
    ("Set / build dataset", action_dataset),
    ("Configure hyperparameters", action_hyperparams),
    ("Token audit (CPU, verify prompts fit)", action_audit),
    ("Smoke train (short sanity run)", action_smoke),
    ("Full train", action_full),
    ("Evaluate trained adapter (local)", action_evaluate),
    ("Distill from Jev (teacher-label train set)", action_distill),
    ("Compare vs Jev API", action_compare_jev),
    ("Show results (your model vs Jev)", action_show_results),
    ("Save config", action_save),
    ("Load config", action_load),
]


def print_header(config: dict[str, Any]) -> None:
    iters = full_iters(config)
    print("\n" + "=" * 68)
    print(" Router Studio — turn any model into a Jev-style calibrated router")
    print("=" * 68)
    print(f" base model : {config['base_model']}")
    print(f" routing    : {config['routing_mode']}")
    print(f" dataset    : {config['data_dir']}  (train={dataset_train_count(config)})")
    print(f" adapter    : {config['adapter_dir']}  ready={adapter_ready(config)}")
    print(f" hyperparams: layers={config['num_layers']} rank={config['rank']} "
          f"lr={config['learning_rate']} accum={config['gradient_accumulation']} "
          f"maxlen={config['max_length']}")
    print(f" full iters : {iters}  (epochs={config['epochs_full']})   smoke iters: {config['smoke_iters']}")
    print("-" * 68)


def main() -> None:
    config = load_config()
    while True:
        print_header(config)
        for index, (label, _) in enumerate(MENU, start=1):
            print(f" {index:>2}) {label}")
        print("  0) Quit")
        choice = ask("\nSelect", "0")
        if choice == "0":
            print("Bye.")
            return
        try:
            index = int(choice)
        except ValueError:
            print("Enter a number.")
            continue
        if not 1 <= index <= len(MENU):
            print("Out of range.")
            continue
        try:
            MENU[index - 1][1](config)
        except KeyboardInterrupt:
            print("\n(interrupted; back to menu)")
        except Exception as error:  # keep the TUI alive on any action failure
            print(f"\nAction failed: {error}")
        pause()


if __name__ == "__main__":
    main()
