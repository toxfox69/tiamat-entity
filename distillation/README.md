# TIAMAT Self-Distillation

Training data is collected in /root/.automaton/training_data/
When 5000+ examples are ready, distillation can begin.

- training_full_{date}.jsonl — Complete exported dataset
- training_quality_{date}.jsonl — Filtered high-quality subset
- manifest_{date}.json — Training run configuration
- distillation_status.json — Current/last training job status
- versions/ — Model version history and benchmarks
