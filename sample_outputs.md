# Sample Outputs: Base vs Fine-tuned Model

本文件展示 Base Model（SmolLM2-1.7B-Instruct）與 Fine-tuned Model（LoRA 微調後）的輸出比較。

**產生方式**：執行 `scripts/finetune/compare_outputs.ipynb` 的「Generate sample_outputs.md」cell 後，會自動產生完整內容並覆寫本文件。

---

## Decision Accuracy Summary

（執行 compare_outputs.ipynb 後會填入）

- **Base model**: -
- **Fine-tuned model**: -

---

## Example Outputs

（執行 compare_outputs.ipynb 後會填入數題完整對照）

---

## Discussion

- **格式**：Fine-tuned 模型應更穩定輸出符合 Tree of Thought 的 JSON 結構。
- **推理**：微調後模型對 n_games、p_over/p_under、starter vs bench 等統計的詮釋應更貼近訓練資料。
- **決策**：可觀察 decision 準確率是否提升，以及 confidence 是否更合理。
