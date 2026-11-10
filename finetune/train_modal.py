"""LoRA fine-tuning of Qwen3-4B-Instruct-2507 on Modal, plus batch generation for evaluation.

Run through the Modal CLI (it is not a project dependency):
  uvx --from modal modal run finetune/train_modal.py --mode smoke      # 20 steps, ~minutes
  uvx --from modal modal run finetune/train_modal.py --mode train      # full run
  uvx --from modal modal run finetune/train_modal.py --mode generate --file val   # predictions

The adapter is saved to the Modal volume `lattice-finetune`; model weights are never committed.
Heavy imports happen inside the remote functions so this file also loads on a plain machine.
"""

from __future__ import annotations

import json
from pathlib import Path

import modal

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
GPU = "A10G"
HERE = Path(__file__).parent
DATA = HERE / "data"

app = modal.App("lattice-finetune")
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "torch", "transformers>=4.51,<5", "peft>=0.13", "accelerate>=1.0", "sentencepiece"
)
outputs = modal.Volume.from_name("lattice-finetune", create_if_missing=True)
hf_cache = modal.Volume.from_name("lattice-hf-cache", create_if_missing=True)
VOLUMES = {"/out": outputs, "/root/.cache/huggingface": hf_cache}

HYPER = {
    "lora_r": 16, "lora_alpha": 32, "lora_dropout": 0.05, "lr": 2e-4, "epochs": 2,
    "per_device_batch": 8, "grad_accum": 2, "max_len": 1024, "warmup_ratio": 0.03, "seed": 7,
}  # fmt: skip
TARGET_MODULES = ["q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"]


def _encode(tok, messages: list[dict], max_len: int) -> dict:
    """Tokenize one chat; only the assistant reply counts toward the loss."""
    prompt = tok.apply_chat_template(messages[:2], add_generation_prompt=True, tokenize=False)
    full = prompt + messages[2]["content"] + "<|im_end|>\n"
    p_ids = tok(prompt, add_special_tokens=False)["input_ids"]
    f_ids = tok(full, add_special_tokens=False)["input_ids"][:max_len]
    labels = ([-100] * len(p_ids) + f_ids[len(p_ids) :])[: len(f_ids)]
    return {"input_ids": f_ids, "labels": labels}


@app.function(image=image, gpu=GPU, volumes=VOLUMES, timeout=4 * 3600)
def train(rows: list[dict], run_name: str, max_steps: int = -1) -> dict:
    import time

    import torch
    from peft import LoraConfig, get_peft_model
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        Trainer,
        TrainingArguments,
    )

    h = HYPER
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.bfloat16, attn_implementation="sdpa"
    )
    model.gradient_checkpointing_enable()
    model.enable_input_require_grads()
    model = get_peft_model(
        model,
        LoraConfig(
            r=h["lora_r"],
            lora_alpha=h["lora_alpha"],
            lora_dropout=h["lora_dropout"],
            target_modules=TARGET_MODULES,
            task_type="CAUSAL_LM",
        ),  # fmt: skip
    )
    model.print_trainable_parameters()
    data = [_encode(tok, r["messages"], int(h["max_len"])) for r in rows]
    print(f"{len(data)} examples, longest {max(len(d['input_ids']) for d in data)} tokens")

    def collate(batch: list[dict]) -> dict:
        n = max(len(b["input_ids"]) for b in batch)
        pad = tok.pad_token_id
        ids = torch.tensor([b["input_ids"] + [pad] * (n - len(b["input_ids"])) for b in batch])
        lab = torch.tensor([b["labels"] + [-100] * (n - len(b["labels"])) for b in batch])
        mask = torch.tensor(
            [[1] * len(b["input_ids"]) + [0] * (n - len(b["input_ids"])) for b in batch]
        )
        return {"input_ids": ids, "labels": lab, "attention_mask": mask}

    out_dir = f"/out/{run_name}"
    args = TrainingArguments(
        output_dir=out_dir, per_device_train_batch_size=h["per_device_batch"],
        gradient_accumulation_steps=h["grad_accum"], num_train_epochs=h["epochs"],
        max_steps=max_steps, learning_rate=h["lr"], lr_scheduler_type="cosine",
        warmup_ratio=h["warmup_ratio"], bf16=True, logging_steps=10, save_strategy="no",
        report_to=[], seed=h["seed"], remove_unused_columns=False, dataloader_drop_last=True,
    )  # fmt: skip
    t0 = time.time()
    result = Trainer(model=model, args=args, train_dataset=data, data_collator=collate).train()
    secs = time.time() - t0
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    (Path(out_dir) / "train_meta.json").write_text(
        json.dumps(
            {
                "hyper": h,
                "rows": len(data),
                "seconds": secs,
                "base": BASE_MODEL,
                "max_steps": max_steps,
            }
        )
    )
    outputs.commit()
    return {
        "train_loss": result.training_loss,
        "seconds": round(secs),
        "steps": result.global_step,
        "gpu": GPU,
    }


@app.function(image=image, gpu=GPU, volumes=VOLUMES, timeout=2 * 3600)
def generate(prompts: list[list[dict]], run_name: str, batch_size: int = 16) -> list[str]:
    """Greedy-decode a JSON intent for each [system, user] message pair."""
    import torch
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    tok.padding_side = "left"
    model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.bfloat16)
    if run_name != "base":
        outputs.reload()
        model = PeftModel.from_pretrained(model, f"/out/{run_name}")
    model.to("cuda").eval()
    results: list[str] = []
    for i in range(0, len(prompts), batch_size):
        texts = [
            tok.apply_chat_template(m, add_generation_prompt=True, tokenize=False)
            for m in prompts[i : i + batch_size]
        ]
        enc = tok(texts, return_tensors="pt", padding=True, add_special_tokens=False).to("cuda")
        with torch.no_grad():
            out = model.generate(
                **enc, max_new_tokens=320, do_sample=False, pad_token_id=tok.pad_token_id
            )
        results += [
            tok.decode(o[enc["input_ids"].shape[1] :], skip_special_tokens=True) for o in out
        ]
    return results


def _load(name: str) -> list[dict]:
    return [
        json.loads(line)
        for line in (DATA / f"{name}.jsonl").read_text().splitlines()
        if line.strip()
    ]


@app.local_entrypoint()
def main(mode: str = "smoke", run_name: str = "", file: str = "val", limit: int = 0) -> None:
    if mode in ("smoke", "train"):
        rows = _load("train")
        if mode == "smoke":
            rows = rows[:320]
        name = run_name or ("smoke" if mode == "smoke" else "qwen3-4b-lattice-v1")
        print(train.remote(rows, name, max_steps=20 if mode == "smoke" else -1))
    elif mode == "generate":
        rows = _load(file)[: limit or None]
        preds = generate.remote(
            [r["messages"][:2] for r in rows], run_name or "qwen3-4b-lattice-v1"
        )
        out = DATA / f"preds_{run_name or 'qwen3-4b-lattice-v1'}_{file}.jsonl"
        out.write_text(
            "".join(
                json.dumps({"row": r, "pred": p}) + "\n" for r, p in zip(rows, preds, strict=True)
            )
        )
        print("wrote", out)
    else:
        raise SystemExit(f"unknown mode {mode!r}")
