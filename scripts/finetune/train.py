#!/usr/bin/env python3
import json
from pathlib import Path

import torch
from datasets import Dataset
from peft import LoraConfig, get_peft_model, TaskType
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    TrainingArguments,
    Trainer,
)

# =============================
# Paths (KEEP SAME AS NOTEBOOK)
# =============================
project_root = Path.cwd()
if project_root.name == "finetune":
    project_root = project_root.parent.parent
elif project_root.name == "scripts":
    project_root = project_root.parent

data_dir = project_root / "data"
output_dir = project_root / "outputs"
output_dir.mkdir(parents=True, exist_ok=True)

train_path = data_dir / "train.jsonl"
adapter_path = output_dir / "smollm2-bet-advisor"

print(f"Project root: {project_root}")
print(f"Train: {train_path} (exists: {train_path.exists()})")
print(f"Adapter output: {adapter_path}")

if not train_path.exists():
    raise FileNotFoundError(f"Train file not found: {train_path}")

# =============================
# DeepSpeed config (ZeRO-3 + CPU offload)
# =============================
ds_config = {
  "train_micro_batch_size_per_gpu": 1,
  "gradient_accumulation_steps": 8,

  "zero_optimization": {
    "stage": 2,
    "offload_optimizer": { "device": "cpu", "pin_memory": True },
    "contiguous_gradients": True,
    "overlap_comm": True,
    "reduce_bucket_size": 50000000
  }
}

ds_path = output_dir / "ds_zero3_offload.json"
ds_path.write_text(json.dumps(ds_config, indent=2), encoding="utf-8")
print(f"DeepSpeed config: {ds_path}")

# =============================
# Prompts / data loading
# =============================
SYSTEM_PROMPT = """You are an expert NBA player data analyst. Your task is to analyze betting questions (over/under) using historical player statistics.

## Tree of Thought Reasoning Framework

Build your reasoning as a tree with these main branches (evaluate each, then synthesize):

1. **Sample & Statistics Branch**: For each context filter (all games, last N games, starter vs bench, with/without star teammates), assess:
   - n_games: Is sample size sufficient? (n < 10 → low weight)
   - p_over, p_under, mean, std: Which context favors over vs under?
   - Conflict between contexts → note uncertainty

2. **Lineup/Teammate Branch**: How does starter vs bench, or with/without star teammates, change the stats? Does lineup context support or contradict the main trend?

3. **Risk & Synthesis Branch**: Given the above, what is the net signal? If branches conflict or sample is weak → prefer "avoid".

## Output Format (JSON only, no markdown)

{
  "decision": "over" | "under" | "avoid",
  "confidence": 0.0 to 1.0,
  "reasoning": {
    "tree_of_thought": [
      {"step": 1, "branch": "sample_stats", "thought": "...", "conclusion": "..."},
      {"step": 2, "branch": "lineup_teammate", "thought": "...", "conclusion": "..."},
      {"step": 3, "branch": "synthesis", "thought": "...", "conclusion": "..."}
    ]
  },
  "summary": "One-sentence conclusion"
}

Each step must have: branch (which dimension), thought (your analysis), conclusion (what this branch implies for the decision).
Respond with ONLY valid JSON, no markdown or extra text."""

def load_jsonl(path: Path) -> list[dict]:
    items: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(json.loads(line))
    return items

train_data = load_jsonl(train_path)
print(f"Train: {len(train_data)} records")
if train_data:
    ex = train_data[0]
    print(f"  instruction: {ex.get('instruction','')[:60]}...")
    print(f"  input: {len(ex.get('input',''))} chars, output: {len(ex.get('output',''))} chars")

# =============================
# Model / tokenizer
# =============================
MODEL_ID = "HuggingFaceTB/SmolLM2-1.7B-Instruct"
print(f"Loading tokenizer: {MODEL_ID}")
tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token

print(f"Loading model: {MODEL_ID}")
# NOTE: GTX 1080 does NOT support bf16. Use fp16 on GPU.
model = AutoModelForCausalLM.from_pretrained(
    MODEL_ID,
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
    trust_remote_code=True,
)

# =============================
# Tokenization (same logic as notebook)
# =============================
MAX_SEQ_LENGTH = 4096  

def format_training_example(item: dict) -> dict:
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"{item['instruction']}\n\nStatistics:\n{item['input']}"},
        {"role": "assistant", "content": item["output"]},
    ]

    full_text = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=False
    )

    prompt_messages = messages[:-1]
    prompt_text = tokenizer.apply_chat_template(
        prompt_messages, tokenize=False, add_generation_prompt=True
    )
    prompt_ids = tokenizer(prompt_text, return_tensors="pt", add_special_tokens=False)
    prompt_len = prompt_ids.input_ids.shape[1]

    full_ids = tokenizer(
        full_text,
        return_tensors="pt",
        truncation=True,
        max_length=MAX_SEQ_LENGTH,
        padding=False,
    )
    input_ids = full_ids.input_ids[0]
    labels = input_ids.clone()
    labels[:prompt_len] = -100

    return {
        "input_ids": input_ids,
        "labels": labels,
        "attention_mask": full_ids.attention_mask[0],
    }

tokenized = [format_training_example(item) for item in train_data]
print(f"Tokenized {len(tokenized)} examples")
if tokenized:
    print(f"Example input_ids length: {len(tokenized[0]['input_ids'])}")

def to_dataset_format(tok_list):
    return {
        "input_ids": [t["input_ids"].tolist() for t in tok_list],
        "labels": [t["labels"].tolist() for t in tok_list],
        "attention_mask": [t["attention_mask"].tolist() for t in tok_list],
    }

ds_dict = to_dataset_format(tokenized)
train_dataset = Dataset.from_dict(ds_dict)

data_collator = DataCollatorForSeq2Seq(
    tokenizer=tokenizer,
    model=model,
    padding=True,
    return_tensors="pt",
    label_pad_token_id=-100,
)

print(f"Dataset: {train_dataset}")

# =============================
# LoRA
# =============================
lora_config = LoraConfig(
    r=8,
    lora_alpha=32,
    target_modules=["q_proj", "v_proj", "o_proj"],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
)
model = get_peft_model(model, lora_config)
model.print_trainable_parameters()

# =============================
# Memory savers
# =============================
model.gradient_checkpointing_enable()
model.config.use_cache = False

# =============================
# Training
# =============================
training_args = TrainingArguments(
    output_dir=str(adapter_path),
    num_train_epochs=3,
    per_device_train_batch_size=1,
    gradient_accumulation_steps=8,
    learning_rate=2e-5,
    warmup_ratio=0.1,
    logging_steps=10,
    save_strategy="epoch",
    save_total_limit=2,
    bf16=False,
    fp16=False,
    report_to="none",
    deepspeed=str(ds_path),
)

trainer = Trainer(
    model=model,
    args=training_args,
    train_dataset=train_dataset,
    data_collator=data_collator,
)

def main():
    print("Starting training...")
    trainer.train()
    trainer.save_model(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))
    print(f"Saved adapter and tokenizer to: {adapter_path}")

if __name__ == "__main__":
    main()
