"""Audit, train, and evaluate a Nimble-style finance router with MLX.

The module keeps MLX imports inside runtime functions so ``audit`` remains
usable in the headless Codex environment. Run ``train`` from a normal macOS
Terminal where Metal is available.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import shutil
import time
from dataclasses import asdict
from functools import partial
from pathlib import Path
from typing import Any, Iterator

from agent_os.safe_path import SecurityError, validated_path
from model_training.finance_candidate_router.common import (
    EncodedDecision,
    SYSTEM_PROMPT,
    ValidationLossTracker,
    encode_decision,
    read_jsonl,
    sha256_json,
    stable_permutation,
)
from model_training.finance_candidate_router.direct_common import (
    DIRECT_SYSTEM_PROMPT,
    encode_direct_decision,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA = (
    REPO_ROOT
    / "enterprise_root/tenants/company/training_data/finance_router_candidate_v1"
)
DEFAULT_DIRECT_DATA = (
    REPO_ROOT
    / "enterprise_root/tenants/company/training_data/finance_router_direct_candidate_v1"
)
# No portable default: set FINANCE_ROUTER_BASE_MODEL or pass --model.
_DEFAULT_MODEL_ENV = os.environ.get("FINANCE_ROUTER_BASE_MODEL", "").strip()
try:
    DEFAULT_MODEL = validated_path(_DEFAULT_MODEL_ENV, label="FINANCE_ROUTER_BASE_MODEL") if _DEFAULT_MODEL_ENV else None
except SecurityError:
    DEFAULT_MODEL = None  # invalid value: require --model explicitly
DEFAULT_ADAPTER = REPO_ROOT / "adapters/finance_candidate_router_qwen25_1p5b_v1"


def default_data_dir(routing_mode: str) -> Path:
    """Default dataset for a routing mode — direct and hierarchical ship different
    data contracts, so the default must track the selected mode (never silently
    feed two-stage rows to a direct task, or vice versa)."""
    return DEFAULT_DIRECT_DATA if routing_mode == "direct" else DEFAULT_DATA

TASK_DEFINITIONS = {
    "hierarchical": {
        "task": "finance_hierarchical_candidate_classification_v1",
        "system_prompt": SYSTEM_PROMPT,
        "encoder": encode_decision,
        "prompt_source": Path(__file__).with_name("common.py"),
    },
    "direct": {
        "task": "finance_direct_50_choice_candidate_classification_v1",
        "system_prompt": DIRECT_SYSTEM_PROMPT,
        "encoder": encode_direct_decision,
        "prompt_source": Path(__file__).with_name("direct_common.py"),
    },
}


def task_definition(routing_mode: str) -> dict[str, Any]:
    return TASK_DEFINITIONS[routing_mode]


def routing_mode_for_task(task: str) -> str:
    for mode, definition in TASK_DEFINITIONS.items():
        if definition["task"] == task:
            return mode
    raise ValueError(f"Unsupported adapter task contract: {task!r}")


class EarlyStoppingRequested(RuntimeError):
    """Internal signal used to stop MLX training after validation plateaus."""


def save_trainable_adapter(model: Any, path: Path) -> None:
    """Save only trainable LoRA parameters using the MLX-LM adapter format."""
    import mlx.core as mx
    from mlx.utils import tree_flatten

    weights = dict(tree_flatten(model.trainable_parameters()))
    mx.save_safetensors(str(path), weights)


class BestValidationCheckpoint:
    """Persist the lowest-validation-loss adapter and request early stopping."""

    def __init__(
        self,
        model: Any,
        adapter_path: Path,
        *,
        patience: int,
        min_delta: float,
    ) -> None:
        self.model = model
        self.adapter_path = adapter_path
        self.best_path = adapter_path / "best_adapters.safetensors"
        self.status_path = adapter_path / "checkpoint_selection.json"
        self.tracker = ValidationLossTracker(patience=patience, min_delta=min_delta)

    def write_status(self, stopped_early: bool = False) -> None:
        status = {
            "selection_metric": "validation_loss",
            "mode": "min",
            "patience": self.tracker.patience,
            "min_delta": self.tracker.min_delta,
            "best_iteration": self.tracker.best_iteration,
            "best_loss": self.tracker.best_loss,
            "non_improving_evaluations": self.tracker.non_improving_evaluations,
            "stopped_early": stopped_early,
            "history": self.tracker.history,
            "best_checkpoint": self.best_path.name,
            "deployment_checkpoint": "adapters.safetensors",
            "last_checkpoint": "last_adapters.safetensors",
        }
        self.status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    def on_train_loss_report(self, train_info: dict[str, Any]) -> None:
        del train_info

    def record_validation(
        self,
        iteration: int,
        val_loss: float,
        *,
        allow_early_stop: bool,
    ) -> None:
        improved, should_stop = self.tracker.observe(iteration, val_loss)
        if improved:
            save_trainable_adapter(self.model, self.best_path)
            print(
                f"Iter {iteration}: New best validation loss {val_loss:.6f}; "
                f"saved {self.best_path}.",
                flush=True,
            )
        should_request_stop = allow_early_stop and should_stop
        self.write_status(stopped_early=should_request_stop)
        if should_request_stop:
            raise EarlyStoppingRequested(
                f"Validation loss did not improve by at least {self.tracker.min_delta:g} "
                f"for {self.tracker.patience} evaluations"
            )

    def on_val_loss_report(self, val_info: dict[str, Any]) -> None:
        self.record_validation(
            int(val_info["iteration"]),
            float(val_info["val_loss"]),
            allow_early_stop=True,
        )


def load_tokenizer(model_path: Path) -> Any:
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=True)


def encode_split(
    data_dir: Path,
    split: str,
    tokenizer: Any,
    *,
    seed: int,
    max_length: int,
    routing_mode: str = "hierarchical",
) -> list[EncodedDecision]:
    rows = read_jsonl(data_dir / f"{split}.jsonl")
    encoder = task_definition(routing_mode)["encoder"]
    return [encoder(row, tokenizer, seed=seed, max_length=max_length) for row in rows]


def audit_dataset(
    data_dir: Path,
    model_path: Path,
    seed: int,
    max_length: int,
    routing_mode: str = "hierarchical",
) -> dict[str, Any]:
    tokenizer = load_tokenizer(model_path)
    definition = task_definition(routing_mode)
    report: dict[str, Any] = {
        "model_path": str(model_path),
        "routing_mode": routing_mode,
        "task": definition["task"],
        "seed": seed,
        "max_length": max_length,
        "system_prompt_sha256": hashlib.sha256(
            definition["system_prompt"].encode("utf-8")
        ).hexdigest(),
        "splits": {},
    }
    all_families: dict[str, set[str]] = {}
    for split in ("train", "valid", "test"):
        encoded = encode_split(
            data_dir,
            split,
            tokenizer,
            seed=seed,
            max_length=max_length,
            routing_mode=routing_mode,
        )
        lengths = [len(row.input_ids) for row in encoded]
        target_positions: dict[int, int] = {}
        for row in encoded:
            target_positions[row.target_index] = target_positions.get(row.target_index, 0) + 1
        all_families[split] = {row.family for row in encoded}
        report["splits"][split] = {
            "records": len(encoded),
            "families": len(all_families[split]),
            "min_prompt_tokens": min(lengths),
            "max_prompt_tokens": max(lengths),
            "mean_prompt_tokens": round(sum(lengths) / len(lengths), 2),
            "max_candidates": max(len(row.candidate_token_ids) for row in encoded),
            "target_index_counts": dict(sorted(target_positions.items())),
            "encoded_sha256": sha256_json([asdict(row) for row in encoded]),
        }
    for left, right in (("train", "valid"), ("train", "test"), ("valid", "test")):
        overlap = all_families[left] & all_families[right]
        if overlap:
            raise ValueError(f"Family leakage between {left} and {right}: {sorted(overlap)[:5]}")
    return report


def decision_batches(
    dataset: list[EncodedDecision],
    batch_size: int,
    max_seq_length: int,
    loop: bool = False,
    seed: int | None = None,
    comm_group: Any = None,
) -> Iterator[tuple[Any, Any, Any]]:
    """Yield batch-one decisions without padding contaminating the answer position."""
    del comm_group
    if batch_size != 1:
        raise ValueError("Candidate trainer currently requires --batch-size 1; use gradient accumulation")
    import mlx.core as mx

    base_seed = 0 if seed is None else seed
    epoch = 0
    while True:
        # Reproducible per-epoch order (hash-based, no `random` module).
        order = stable_permutation(len(dataset), f"{base_seed}:epoch{epoch}")
        epoch += 1
        for index in order:
            row = dataset[index]
            if len(row.input_ids) > max_seq_length:
                raise ValueError(f"{row.record_id}: sequence exceeds max length; truncation is forbidden")
            yield (
                mx.array([row.input_ids], dtype=mx.int32),
                mx.array([row.candidate_token_ids], dtype=mx.int32),
                mx.array([row.target_index], dtype=mx.int32),
            )
        if not loop:
            return


def _output_rows(model: Any, candidate_ids: Any) -> Any:
    """Read and, if necessary, dequantize only the requested LM-head rows."""
    import mlx.core as mx

    if getattr(model.args, "tie_word_embeddings", False):
        head = model.model.embed_tokens
    else:
        head = model.lm_head
    weight = head.weight[candidate_ids]
    if hasattr(head, "scales"):
        kwargs = {
            "group_size": head.group_size,
            "bits": head.bits,
        }
        if hasattr(head, "mode"):
            kwargs["mode"] = head.mode
        biases = getattr(head, "biases", None)
        selected_biases = biases[candidate_ids] if biases is not None else None
        weight = mx.dequantize(
            weight,
            scales=head.scales[candidate_ids],
            biases=selected_biases,
            **kwargs,
        )
    return weight


def candidate_logits(model: Any, input_ids: Any, candidate_ids: Any) -> Any:
    """Run the transformer once and project only allowed answer rows."""
    import mlx.core as mx

    hidden = model.model(input_ids)[:, -1, :].astype(mx.float32)
    # Batch size is deliberately one, so remove its candidate-id dimension.
    rows = _output_rows(model, candidate_ids[0]).astype(mx.float32)
    return hidden @ rows.T


def candidate_loss(model: Any, input_ids: Any, candidate_ids: Any, target_index: Any) -> tuple[Any, Any]:
    import mlx.core as mx
    import mlx.nn as nn

    logits = candidate_logits(model, input_ids, candidate_ids)
    loss = nn.losses.cross_entropy(logits, target_index, reduction="mean").astype(mx.float32)
    return loss, mx.array(input_ids.shape[0], dtype=mx.int32)


def evaluate_accuracy(model: Any, dataset: list[EncodedDecision], max_length: int) -> dict[str, Any]:
    import mlx.core as mx

    model.eval()
    results = []
    total_loss = 0.0
    started = time.perf_counter()
    for row in dataset:
        if len(row.input_ids) > max_length:
            raise ValueError(f"{row.record_id}: sequence exceeds max length")
        input_ids = mx.array([row.input_ids], dtype=mx.int32)
        candidate_ids = mx.array([row.candidate_token_ids], dtype=mx.int32)
        target = mx.array([row.target_index], dtype=mx.int32)
        logits = candidate_logits(model, input_ids, candidate_ids)[0]
        probabilities = mx.softmax(logits)
        mx.eval(logits, probabilities)
        prediction_index = int(mx.argmax(logits).item())
        gold = int(target[0].item())
        probability_values = probabilities.tolist()
        nll = -__import__("math").log(max(probability_values[gold], 1e-30))
        brier = sum((probability - float(index == gold)) ** 2 for index, probability in enumerate(probability_values))
        ranked = sorted(probability_values, reverse=True)
        total_loss += nll
        results.append(
            {
                "id": row.record_id,
                "stage": row.stage,
                "family": row.family,
                "source_id": row.source_id,
                "target": row.target,
                "prediction": row.choices[prediction_index],
                "correct": prediction_index == gold,
                "confidence": probability_values[prediction_index],
                "margin": ranked[0] - ranked[1] if len(ranked) > 1 else 1.0,
                "target_probability": probability_values[gold],
                "nll": nll,
                "brier": brier,
                "probabilities": dict(zip(row.choices, probability_values)),
            }
        )
    stages: dict[str, dict[str, Any]] = {}
    for stage in sorted({row["stage"] for row in results}):
        selected = [row for row in results if row["stage"] == stage]
        stages[stage] = {
            "records": len(selected),
            "correct": sum(row["correct"] for row in selected),
            "accuracy": sum(row["correct"] for row in selected) / len(selected),
            "mean_nll": sum(row["nll"] for row in selected) / len(selected),
            "mean_brier": sum(row["brier"] for row in selected) / len(selected),
        }
    paired: dict[str, list[dict[str, Any]]] = {}
    for result in results:
        paired.setdefault(result["source_id"], []).append(result)
    end_to_end_rows = [values for values in paired.values() if {row["stage"] for row in values} == {"domain", "skill"}]
    end_to_end_correct = sum(all(row["correct"] for row in values) for values in end_to_end_rows)
    calibration_bins = []
    for lower_index in range(10):
        lower = lower_index / 10
        upper = (lower_index + 1) / 10
        selected = [
            row for row in results
            if lower <= row["confidence"] < upper or (upper == 1.0 and row["confidence"] == 1.0)
        ]
        if not selected:
            continue
        accuracy = sum(row["correct"] for row in selected) / len(selected)
        mean_confidence = sum(row["confidence"] for row in selected) / len(selected)
        calibration_bins.append(
            {
                "lower": lower,
                "upper": upper,
                "records": len(selected),
                "accuracy": accuracy,
                "mean_confidence": mean_confidence,
                "absolute_gap": abs(accuracy - mean_confidence),
            }
        )
    ece = sum(item["records"] * item["absolute_gap"] for item in calibration_bins) / len(results)
    coverage = {}
    for threshold in (0.5, 0.7, 0.8, 0.9, 0.95):
        selected = [row for row in results if row["confidence"] >= threshold]
        coverage[str(threshold)] = {
            "records": len(selected),
            "coverage": len(selected) / len(results),
            "accuracy": (sum(row["correct"] for row in selected) / len(selected)) if selected else None,
        }
    confusion_counts: dict[tuple[str, str], int] = {}
    for row in results:
        if not row["correct"]:
            key = (row["target"], row["prediction"])
            confusion_counts[key] = confusion_counts.get(key, 0) + 1
    confusions = [
        {"target": target, "prediction": prediction, "count": count}
        for (target, prediction), count in sorted(confusion_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "records": len(results),
        "correct": sum(row["correct"] for row in results),
        "accuracy": sum(row["correct"] for row in results) / len(results),
        "mean_nll": total_loss / len(results),
        "mean_brier": sum(row["brier"] for row in results) / len(results),
        "expected_calibration_error": ece,
        "elapsed_seconds": time.perf_counter() - started,
        "stages": stages,
        "end_to_end": {
            "records": len(end_to_end_rows),
            "correct": end_to_end_correct,
            "accuracy": end_to_end_correct / len(end_to_end_rows) if end_to_end_rows else None,
        },
        "coverage_at_confidence": coverage,
        "calibration_bins": calibration_bins,
        "confusions": confusions,
        "rows": results,
    }


def configure_lora(model: Any, num_layers: int, rank: int, dropout: float, scale: float) -> None:
    from mlx_lm.tuner.utils import linear_to_lora_layers, print_trainable_parameters

    model.freeze()
    if not 1 <= num_layers <= len(model.layers):
        raise ValueError(f"num_layers must be 1..{len(model.layers)}")
    linear_to_lora_layers(
        model,
        num_layers,
        {"rank": rank, "dropout": dropout, "scale": scale},
        use_dora=False,
    )
    print_trainable_parameters(model)


def train_command(args: argparse.Namespace) -> None:
    import mlx.core as mx
    import mlx.optimizers as optim
    from mlx_lm import load
    from mlx_lm.tuner.trainer import TrainingArgs, evaluate, train

    args.adapter_path.mkdir(parents=True, exist_ok=True)
    definition = task_definition(args.routing_mode)
    audit = audit_dataset(
        args.data_dir,
        args.model,
        args.seed,
        args.max_length,
        routing_mode=args.routing_mode,
    )
    (args.adapter_path / "token_audit.json").write_text(json.dumps(audit, indent=2) + "\n")

    print(f"Loading model: {args.model}", flush=True)
    model, tokenizer = load(str(args.model), tokenizer_config={"trust_remote_code": True})
    train_data = encode_split(
        args.data_dir,
        "train",
        tokenizer,
        seed=args.seed,
        max_length=args.max_length,
        routing_mode=args.routing_mode,
    )
    valid_data = encode_split(
        args.data_dir,
        "valid",
        tokenizer,
        seed=args.seed,
        max_length=args.max_length,
        routing_mode=args.routing_mode,
    )
    configure_lora(model, args.num_layers, args.rank, args.dropout, args.scale)

    contract = {
        "task": definition["task"],
        "routing_mode": args.routing_mode,
        "model": str(args.model),
        "data": str(args.data_dir),
        "system_prompt": definition["system_prompt"],
        "prompt_code_sha256": hashlib.sha256(
            definition["prompt_source"].read_bytes()
        ).hexdigest(),
        "seed": args.seed,
        "max_length": args.max_length,
        "num_layers": args.num_layers,
        "lora_parameters": {"rank": args.rank, "dropout": args.dropout, "scale": args.scale},
        "learning_rate": args.learning_rate,
        "batch_size": 1,
        "gradient_accumulation_steps": args.gradient_accumulation,
        "iterations": args.iters,
        "checkpoint_selection": {
            "metric": "validation_loss",
            "mode": "min",
            "early_stopping_patience": args.early_stopping_patience,
            "min_delta": args.min_delta,
        },
        "candidate_projection": "selected_output_rows_fp32",
        "mlx_version": importlib.metadata.version("mlx"),
        "mlx_lm_version": importlib.metadata.version("mlx-lm"),
    }
    # Compatible with mlx_lm.tuner.utils.load_adapters plus our extra contract fields.
    adapter_config = {
        **contract,
        "fine_tune_type": "lora",
        "num_layers": args.num_layers,
        "lora_parameters": {"rank": args.rank, "dropout": args.dropout, "scale": args.scale},
    }
    (args.adapter_path / "adapter_config.json").write_text(json.dumps(adapter_config, indent=2) + "\n")

    print("Evaluating base model on validation split...", flush=True)
    before = evaluate_accuracy(model, valid_data, args.max_length)
    (args.adapter_path / "before_validation.json").write_text(json.dumps(before, indent=2) + "\n")
    print(json.dumps({"before": {k: before[k] for k in ("accuracy", "mean_nll", "mean_brier", "expected_calibration_error", "stages", "end_to_end")}}, indent=2))

    optimizer = optim.Adam(learning_rate=args.learning_rate)
    training_args = TrainingArgs(
        batch_size=1,
        iters=args.iters,
        val_batches=-1,
        steps_per_report=args.steps_per_report,
        steps_per_eval=args.steps_per_eval,
        steps_per_save=args.save_every,
        max_seq_length=args.max_length,
        adapter_file=str(args.adapter_path / "adapters.safetensors"),
        grad_checkpoint=args.grad_checkpoint,
        grad_accumulation_steps=args.gradient_accumulation,
        clear_cache_threshold=args.clear_cache_threshold,
    )
    mx.random.seed(args.seed)
    checkpoint_callback = BestValidationCheckpoint(
        model,
        args.adapter_path,
        patience=args.early_stopping_patience,
        min_delta=args.min_delta,
    )
    stopped_early = False
    stop_reason = None
    try:
        train(
            model=model,
            optimizer=optimizer,
            train_dataset=train_data,
            val_dataset=valid_data,
            args=training_args,
            loss=candidate_loss,
            iterate_batches=partial(decision_batches, seed=args.seed),
            training_callback=checkpoint_callback,
        )
    except EarlyStoppingRequested as error:
        stopped_early = True
        stop_reason = str(error)
        print(f"Early stopping: {stop_reason}", flush=True)

    last_path = args.adapter_path / "last_adapters.safetensors"
    save_trainable_adapter(model, last_path)
    if not stopped_early:
        # Final validation runs before the last optimizer step; evaluate once more after the loop.
        print("Evaluating final training state for checkpoint selection...", flush=True)
        final_val_loss = evaluate(
            model=model,
            dataset=valid_data,
            loss=candidate_loss,
            batch_size=1,
            num_batches=-1,
            max_seq_length=args.max_length,
            iterate_batches=partial(decision_batches, seed=args.seed),
        )
        checkpoint_callback.record_validation(
            args.iters,
            float(final_val_loss),
            allow_early_stop=False,
        )
    if not checkpoint_callback.best_path.exists():
        raise RuntimeError("Training completed without creating a best validation checkpoint")
    model.load_weights(str(checkpoint_callback.best_path), strict=False)
    shutil.copyfile(checkpoint_callback.best_path, args.adapter_path / "adapters.safetensors")
    checkpoint_callback.write_status(stopped_early=stopped_early)
    print(
        f"Selected iteration {checkpoint_callback.tracker.best_iteration} with validation "
        f"loss {checkpoint_callback.tracker.best_loss:.6f}; adapters.safetensors now contains "
        "the best checkpoint.",
        flush=True,
    )

    print("Evaluating trained adapter on validation split...", flush=True)
    after = evaluate_accuracy(model, valid_data, args.max_length)
    (args.adapter_path / "after_validation.json").write_text(json.dumps(after, indent=2) + "\n")
    summary = {
        "contract": contract,
        "before": {k: before[k] for k in ("accuracy", "mean_nll", "mean_brier", "expected_calibration_error", "stages", "end_to_end")},
        "after": {k: after[k] for k in ("accuracy", "mean_nll", "mean_brier", "expected_calibration_error", "stages", "end_to_end")},
        "checkpoint_selection": {
            "metric": "validation_loss",
            "best_iteration": checkpoint_callback.tracker.best_iteration,
            "best_loss": checkpoint_callback.tracker.best_loss,
            "stopped_early": stopped_early,
            "stop_reason": stop_reason,
            "deployment_checkpoint": "adapters.safetensors",
            "best_checkpoint": checkpoint_callback.best_path.name,
            "last_checkpoint": last_path.name,
        },
        "test_evaluated": False,
    }
    (args.adapter_path / "run_report.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)


def evaluate_command(args: argparse.Namespace) -> None:
    from mlx_lm import load
    from mlx_lm.tuner.utils import load_adapters

    config = json.loads((args.adapter_path / "adapter_config.json").read_text())
    routing_mode = routing_mode_for_task(config.get("task"))
    if args.data_dir is None:
        args.data_dir = default_data_dir(routing_mode)
    args.data_dir = args.data_dir.resolve()
    definition = task_definition(routing_mode)
    prompt_hash = hashlib.sha256(definition["prompt_source"].read_bytes()).hexdigest()
    if config.get("prompt_code_sha256") != prompt_hash:
        raise ValueError("Prompt code differs from the code used for training")
    model_path = args.model or Path(config["model"])
    model, tokenizer = load(str(model_path), tokenizer_config={"trust_remote_code": True})
    load_adapters(model, str(args.adapter_path))
    dataset = encode_split(
        args.data_dir,
        args.split,
        tokenizer,
        seed=config["seed"],
        max_length=config["max_length"],
        routing_mode=routing_mode,
    )
    report = evaluate_accuracy(model, dataset, config["max_length"])
    output = args.adapter_path / f"{args.split}_evaluation.json"
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("records", "accuracy", "mean_nll", "mean_brier", "expected_calibration_error", "stages", "end_to_end", "coverage_at_confidence", "confusions")}, indent=2))
    print(f"Wrote {output}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    audit = commands.add_parser("audit", help="CPU-only prompt/token audit; does not load MLX")
    audit.add_argument("--data-dir", type=Path, default=None,
                       help="dataset dir; defaults to the dataset matching --routing-mode")
    audit.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    audit.add_argument("--seed", type=int, default=17)
    audit.add_argument("--max-length", type=int, default=2048)
    audit.add_argument(
        "--routing-mode", choices=tuple(TASK_DEFINITIONS), default="hierarchical"
    )
    audit.add_argument("--output", type=Path)

    fit = commands.add_parser("train", help="Train LoRA with candidate-only cross entropy")
    fit.add_argument("--data-dir", type=Path, default=None,
                     help="dataset dir; defaults to the dataset matching --routing-mode")
    fit.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    fit.add_argument("--adapter-path", type=Path, default=DEFAULT_ADAPTER)
    fit.add_argument("--seed", type=int, default=17)
    fit.add_argument("--max-length", type=int, default=2048)
    fit.add_argument(
        "--routing-mode", choices=tuple(TASK_DEFINITIONS), default="hierarchical"
    )
    fit.add_argument("--iters", type=int, default=808)
    fit.add_argument("--learning-rate", type=float, default=2e-5)
    fit.add_argument("--num-layers", type=int, default=8)
    fit.add_argument("--rank", type=int, default=16)
    fit.add_argument("--dropout", type=float, default=0.05)
    fit.add_argument("--scale", type=float, default=2.0, help="LoRA alpha/r; Nimble rank16 alpha32 => 2.0")
    fit.add_argument("--gradient-accumulation", type=int, default=8)
    fit.add_argument("--steps-per-report", type=int, default=25)
    fit.add_argument("--steps-per-eval", type=int, default=100)
    fit.add_argument("--save-every", type=int, default=100)
    fit.add_argument(
        "--early-stopping-patience",
        type=int,
        default=3,
        help="Stop after this many validation checks without improvement; 0 disables stopping",
    )
    fit.add_argument(
        "--min-delta",
        type=float,
        default=1e-4,
        help="Minimum validation-loss decrease counted as an improvement",
    )
    fit.add_argument("--grad-checkpoint", action=argparse.BooleanOptionalAction, default=True)
    fit.add_argument("--clear-cache-threshold", type=int, default=0)

    score = commands.add_parser("evaluate", help="Evaluate a saved adapter")
    score.add_argument("--data-dir", type=Path, default=None,
                       help="dataset dir; defaults to the dataset matching the adapter's routing mode")
    score.add_argument("--adapter-path", type=Path, default=DEFAULT_ADAPTER)
    score.add_argument("--model", type=Path)
    score.add_argument("--split", choices=("valid", "test"), default="valid")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if getattr(args, "model", None) is not None:
        args.model = args.model.resolve()
    if getattr(args, "adapter_path", None) is not None:
        args.adapter_path = args.adapter_path.resolve()
    if args.command in ("audit", "train"):
        if args.data_dir is None:
            args.data_dir = default_data_dir(args.routing_mode)
        args.data_dir = args.data_dir.resolve()
        if args.model is None:
            raise SystemExit(
                "--model is required (or set FINANCE_ROUTER_BASE_MODEL): no portable "
                "default model path exists"
            )
    if args.command == "audit":
        report = audit_dataset(
            args.data_dir,
            args.model,
            args.seed,
            args.max_length,
            routing_mode=args.routing_mode,
        )
        text = json.dumps(report, indent=2) + "\n"
        if args.output:
            args.output.write_text(text)
        print(text, end="")
    elif args.command == "train":
        train_command(args)
    else:
        evaluate_command(args)


if __name__ == "__main__":
    main()
