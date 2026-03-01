#!/usr/bin/env python3
"""
TIAMAT QLoRA Fine-Tuning Script

Fine-tunes Qwen 2.5 7B Instruct on TIAMAT's own behavioral data using QLoRA via unsloth.
Runs on RTX 3090 (24GB VRAM), ~10 minutes for 1,200 examples.

Exports:
  1. LoRA adapter (~200MB) — for incremental updates
  2. Merged 16-bit model (~14GB) — for vLLM serving
  3. GGUF q4_k_m (~4.5GB) — for llama.cpp fallback

Usage: python3 train_tiamat.py [--data /path/to/data.jsonl] [--epochs 3] [--output /workspace/tiamat-lora]
"""

import argparse
import json
import os
import sys
import time

def main():
    parser = argparse.ArgumentParser(description="TIAMAT QLoRA Training")
    parser.add_argument("--data", default="/workspace/tiamat-lora/tiamat_training.jsonl", help="Training data JSONL")
    parser.add_argument("--output", default="/workspace/tiamat-lora", help="Output directory")
    parser.add_argument("--epochs", type=int, default=3, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=2, help="Per-device batch size")
    parser.add_argument("--grad-accum", type=int, default=4, help="Gradient accumulation steps")
    parser.add_argument("--lr", type=float, default=2e-4, help="Learning rate")
    parser.add_argument("--max-seq-len", type=int, default=4096, help="Max sequence length")
    parser.add_argument("--lora-rank", type=int, default=32, help="LoRA rank")
    parser.add_argument("--skip-gguf", action="store_true", help="Skip GGUF export")
    args = parser.parse_args()

    print("=== TIAMAT QLoRA Training ===\n")

    # Verify data exists
    if not os.path.exists(args.data):
        print(f"ERROR: Training data not found: {args.data}")
        sys.exit(1)

    # Count examples
    with open(args.data) as f:
        num_examples = sum(1 for line in f if line.strip())
    print(f"Training data: {num_examples} examples from {args.data}")

    if num_examples < 50:
        print("ERROR: Too few examples (<50). Check export pipeline.")
        sys.exit(1)

    # Import heavy deps after arg parsing
    print("\nLoading model and tokenizer...")
    start = time.time()

    from unsloth import FastLanguageModel
    import torch
    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments

    # Load base model with 4-bit quantization
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name="unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
        max_seq_length=args.max_seq_len,
        dtype=None,  # auto-detect
        load_in_4bit=True,
    )
    print(f"  Model loaded in {time.time() - start:.1f}s")

    # Configure LoRA
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_rank,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_alpha=args.lora_rank,  # alpha = rank (standard)
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",  # 2x speedup
        random_state=42,
    )
    print(f"  LoRA configured: rank={args.lora_rank}, all attn + MLP layers")

    # Load and format training data
    print("\nPreparing dataset...")

    def load_training_data(filepath: str) -> list[dict]:
        """Load JSONL and format as ChatML conversations."""
        examples = []
        with open(filepath) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    messages = data.get("messages", [])
                    if not messages:
                        continue

                    # Format as ChatML string using tokenizer
                    text = tokenizer.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=False,
                    )
                    examples.append({"text": text})
                except (json.JSONDecodeError, Exception):
                    continue
        return examples

    train_data = load_training_data(args.data)
    print(f"  Formatted {len(train_data)} examples")

    if len(train_data) < 50:
        print("ERROR: Too few valid examples after formatting")
        sys.exit(1)

    dataset = Dataset.from_list(train_data)

    # Training
    print(f"\nStarting training: {args.epochs} epochs, batch={args.batch_size}, grad_accum={args.grad_accum}")
    print(f"  Effective batch size: {args.batch_size * args.grad_accum}")
    print(f"  Steps per epoch: ~{len(train_data) // (args.batch_size * args.grad_accum)}")
    print(f"  Total steps: ~{len(train_data) * args.epochs // (args.batch_size * args.grad_accum)}")

    output_dir = os.path.join(args.output, "checkpoints")
    os.makedirs(output_dir, exist_ok=True)

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=TrainingArguments(
            output_dir=output_dir,
            per_device_train_batch_size=args.batch_size,
            gradient_accumulation_steps=args.grad_accum,
            warmup_steps=10,
            num_train_epochs=args.epochs,
            learning_rate=args.lr,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            logging_steps=10,
            optim="adamw_8bit",
            weight_decay=0.01,
            lr_scheduler_type="cosine",
            seed=42,
            save_strategy="epoch",
            report_to="none",
        ),
        max_seq_length=args.max_seq_len,
        dataset_text_field="text",
        packing=True,  # Pack short examples together for efficiency
    )

    train_start = time.time()
    trainer.train()
    train_time = time.time() - train_start
    print(f"\n  Training complete in {train_time:.0f}s ({train_time/60:.1f}min)")

    # Save LoRA adapter
    lora_dir = os.path.join(args.output, "lora")
    print(f"\nSaving LoRA adapter to {lora_dir}...")
    model.save_pretrained(lora_dir)
    tokenizer.save_pretrained(lora_dir)

    # Save merged 16-bit model for vLLM
    merged_dir = os.path.join(args.output, "merged")
    print(f"Saving merged 16-bit model to {merged_dir}...")
    model.save_pretrained_merged(merged_dir, tokenizer, save_method="merged_16bit")

    # Save GGUF for llama.cpp fallback
    gguf_dir = os.path.join(args.output, "gguf") if not args.skip_gguf else None
    if gguf_dir:
        print(f"Saving GGUF q4_k_m to {gguf_dir}...")
        try:
            model.save_pretrained_gguf(gguf_dir, tokenizer, quantization_method="q4_k_m")
        except Exception as exc:
            print(f"  GGUF export failed (non-critical): {exc}")
            gguf_dir = None

    # Write training metadata
    metadata = {
        "base_model": "unsloth/Qwen2.5-7B-Instruct-bnb-4bit",
        "lora_rank": args.lora_rank,
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "grad_accum": args.grad_accum,
        "lr": args.lr,
        "max_seq_len": args.max_seq_len,
        "num_examples": len(train_data),
        "train_time_seconds": round(train_time),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "artifacts": {
            "lora": lora_dir,
            "merged": merged_dir,
            "gguf": gguf_dir,
        },
    }
    meta_path = os.path.join(args.output, "training_metadata.json")
    with open(meta_path, "w") as f:
        json.dump(metadata, f, indent=2)

    print(f"\n=== Training Complete ===")
    print(f"  Examples: {len(train_data)}")
    print(f"  Time: {train_time:.0f}s")
    print(f"  LoRA: {lora_dir}")
    print(f"  Merged: {merged_dir}")
    if gguf_dir:
        print(f"  GGUF: {gguf_dir}")
    print(f"  Metadata: {meta_path}")
    print(f"\nNext: Launch vLLM with serve_tiamat.sh")


if __name__ == "__main__":
    main()
