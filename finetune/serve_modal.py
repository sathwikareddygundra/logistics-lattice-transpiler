"""Serve the tuned adapter for the app's NLU step.

Deploy once:  uvx --from modal modal deploy finetune/serve_modal.py
The container loads the base model plus adapter once and is kept warm for 5 minutes after the
last call (cold start is about a minute). Stop paying with:  uvx --from modal modal app stop lattice-finetune-serve
"""

from __future__ import annotations

import modal

BASE_MODEL = "Qwen/Qwen3-4B-Instruct-2507"
RUN = "qwen3-4b-lattice-v1"

app = modal.App("lattice-finetune-serve")
image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "torch", "transformers>=4.51,<5", "peft>=0.13", "accelerate>=1.0", "sentencepiece"
)
outputs = modal.Volume.from_name("lattice-finetune")
hf_cache = modal.Volume.from_name("lattice-hf-cache")


@app.cls(
    image=image,
    gpu="A10G",
    volumes={"/out": outputs, "/root/.cache/huggingface": hf_cache},
    scaledown_window=300,
    timeout=600,
)
class Tuned:
    @modal.enter()
    def load(self) -> None:
        import torch
        from peft import PeftModel
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(BASE_MODEL)
        model = AutoModelForCausalLM.from_pretrained(BASE_MODEL, torch_dtype=torch.bfloat16)
        self.model = PeftModel.from_pretrained(model, f"/out/{RUN}").to("cuda").eval()

    @modal.method()
    def generate(self, messages: list[dict]) -> str:
        import torch

        text = self.tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
        enc = self.tok(text, return_tensors="pt", add_special_tokens=False).to("cuda")
        with torch.no_grad():
            out = self.model.generate(
                **enc, max_new_tokens=320, do_sample=False, pad_token_id=self.tok.pad_token_id
            )
        return self.tok.decode(out[0][enc["input_ids"].shape[1] :], skip_special_tokens=True)
