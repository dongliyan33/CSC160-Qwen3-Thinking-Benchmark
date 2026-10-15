# CSC160 Qwen3 Thinking Benchmark

A small reproducible Python workflow for comparing Thinking OFF and Thinking ON in a local Ollama **Qwen 3 8B** model. It schedules five mathematical questions, three independent trials per question per condition, for 30 sequential requests. The example questions are demonstrations, not the submitted coursework questions. This repository contains no original predictions, model responses, manual grades, or course assignment documents.

Intended repository name: `CSC160-Qwen3-Thinking-Benchmark`; visibility: **private**. No software license has been selected, so no LICENSE file is included.

## Installation

Use Python **3.9 or newer**. All code uses the Python standard library; `requirements.txt` has no third-party packages. Optional environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
```

Install [Ollama for macOS](https://ollama.com/download/mac), open the Ollama app, and download the model:

```sh
ollama pull qwen3:8b
ollama list
python3 -B benchmark.py verify
```

If no server is running, start `ollama serve` in another terminal. The API must be available at `http://localhost:11434`. No API key or cloud connection is used. See the [official Ollama setup documentation](https://docs.ollama.com/quickstart).

The verification command reads metadata only. The benchmark pins the historical model digest and Ollama version below. A current model tag or newer server might not match; the program stops instead of substituting silently. Exact replication requires the matching model and server. Changing those pins defines a different experiment and must be documented separately. Do not replace a matching installed model merely to follow the download command.

## Exact configuration

| Setting | Value |
| --- | --- |
| Model | `qwen3:8b` |
| Model ID | `500a1f067a9f` |
| Architecture / parameters | Qwen3 / 8,190,735,360 (~8.2B) |
| Quantization | Q4_K_M |
| Ollama version | 0.40.2 |
| Temperature | 0.6 |
| top_k / top_p | 20 / 0.95 |
| repeat_penalty | 1 |
| Context / output token limit | 40960 / 32768 |
| Sampling seed | -1 (fresh stochastic sampling) |
| Order seed | 1602026 |
| keep_alive | 30m |
| Web search / external tools | Disabled / absent |

Full model digest:

```text
500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41
```

`config/model_configuration.json` records these pins without local paths or host metadata. The programs verify the fixed request settings against this file. Full runtime metadata is written only to ignored local experiment data.

## Prepare a new local experiment

```sh
python3 -B benchmark.py init
python3 -B benchmark.py plan
```

`init` makes ignored local input/data files without inference or overwriting existing files. It copies `config/questions.example.json` to `config/questions.json` and creates a blank `config/predictions.md`. `plan` prints the 30-request schedule without contacting Ollama; it does not test mathematical correctness. The examples are approved for a demonstration through `approved_for_experiment: true`. If replacing them, finalize all five questions and explicitly approve that field before running.

Write your own pre-experiment predictions in `config/predictions.md`, remove every TODO, and set `Predictions complete: YES`. No predictions are supplied on your behalf. Optional independently verified reference answers may be kept in ignored `config/reference_answers.json`; neither script reads them.

```sh
python3 -B benchmark.py validate
```

Validation is entirely offline. All paths are relative to the script location, independent of your terminal's current directory.

## Run Thinking OFF and Thinking ON

Only when ready to start a new experiment:

```sh
python3 -B benchmark.py run --approve
```

This one command runs both conditions: 15 OFF (`think: false`) and 15 ON (`think: true`). They are interleaved in a seeded random order and run sequentially. The question and instruction are identical between conditions. Every request has one fresh user message; no previous responses, reference answers, hints, tools, or condition labels are supplied in the message. Thinking is controlled only through the Ollama API flag.

Before the first request, the program freezes predictions, questions, configuration, and scripts, records hashes, and saves the schedule. It verifies the model/server and checks the model digest before every trial. It preserves the original JSON response plus separate final/thinking fields, timestamps, response time, token counts, status, and errors. `data/results.csv` and `data/raw_responses.jsonl` are written incrementally. Grading fields are blank.

There are no automatic retries, and the completed/started-experiment guards prevent accidental reruns. Retain all files after interruption. A dispatched request may have an unknown outcome; do not delete the lock or silently rerun it. Document any later recovery decision separately. Technical errors and truncations are not treated as mathematically wrong answers.

The order seed reproduces the schedule, not identical stochastic answers. Wall time includes loading and HTTP latency; load duration is retained. Output-token counts can include thinking tokens. Keeping model weights loaded does not pass conversational history. Limits and load/cache effects may affect results.

## Manual grading and descriptive summaries

Edit only `grade` and `grading_notes` in `data/results.csv`. Scores: 2 = Correct, 1 = Partially Correct, 0 = Wrong; binary questions use 2 or 0. After all 30 responses are graded:

```sh
python3 -B summarize_results.py
```

The summary checks frozen-input hashes, record IDs, statuses, and raw CSV columns before computing condition/question accuracy, mean score, three-trial score variation, ON-minus-OFF accuracy, mean/median time, and mean output tokens. Accuracy counts only score 2; partial credit affects mean score. Results are saved to ignored `results/` files and SVG charts to `results/figures/`. It does not evaluate model answers, produce a coursework report, or interpret the findings. These small descriptive comparisons do not establish general causal effects.

## Project structure

```text
CSC160-Qwen3-Thinking-Benchmark/
├── README.md
├── benchmark.py
├── summarize_results.py
├── config/
│   ├── questions.example.json
│   └── model_configuration.json
├── results/
│   └── figures/.gitkeep
├── requirements.txt
└── .gitignore
```

`init` creates ignored `config/questions.json`, `config/predictions.md`, and `data/`. Running creates ignored raw data, frozen inputs, audit metadata, and later summaries. The original academic experiment is held in a separate private local archive and is not part of this repository. Inspect `git status` before committing, and do not force-add excluded data. Do not put secrets into tracked files.

## Create the private GitHub repository — only after approval

The prepared folder has an initial local Git commit on `main`, made with a generic project identity (`Benchmark Project <benchmark@example.invalid>`), not a personal identity. No remote is configured and nothing has been pushed. To use your own preferred author identity, configure it locally before future commits. The source ZIP includes `.git` so this prepared commit is retained; extract hidden files too.

Install [GitHub CLI](https://cli.github.com/) if needed. Then, from this directory, after explicitly deciding to publish privately:

```sh
gh auth login
gh auth status
gh repo create CSC160-Qwen3-Thinking-Benchmark --private --source=. --remote=origin --push
```

The last command creates the private repository under the authenticated account and pushes the current local branch; see [GitHub CLI documentation](https://cli.github.com/manual/gh_repo_create). It has not been executed as part of preparation. If the repository name already exists, stop and inspect it instead of overwriting or changing visibility.
