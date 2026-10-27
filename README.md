# DFA Controller: Temporal-Logic Monitoring for AI Control

This repository extends the SHADE-Arena complex sabotage dataset with a monitoring layer built on deterministic finite automata (DFAs). A DFA monitor reads an agent's tool calls, compiles a temporal-logic specification into an automaton, and reports to the LLM monitor when the agent violates a safety rule, misses a goal, or finishes in a bad state.

The aim is to give the LLM monitor structured evidence about what the agent did, so it can judge suspicious behavior with less guesswork.

## What I built

- **`dfa_protocol/`**: The DFA monitoring protocol. It loads LTLf specifications for a task, labels each tool call with atomic propositions, steps one automaton per spec, and writes the results into the monitor's transcript as `ChatDFAControllerMessage` entries.
- **`formula_extractor/`**: A pipeline that turns natural-language task descriptions into normalized requirements and then into LTLf formulas, using an OpenAI-compatible model server and `langextract`.
- **`task_pairs/<task>/dfa/`**: Hand-written specs and a `label.py` for each covered task pair (`api_key_calendar_agendas_2`, `bank_transfer_2`).
- **`protocols/`**: Control protocols (defer to trusted, resample, "claude take the wheel" and their variants) that run alongside the DFA monitor.
- **`plotting_notebooks_protocols/`**: Notebooks for safety, usefulness, and win/lose/continue analysis of the protocols.
- **Batch scripts**: SLURM jobs for generating trajectories and formulas with vLLM (`generate_trajectories_job*.sh`, `generate_formulas_job.sh`).

## How the DFA protocol works

1. **Specs.** Each spec lives in a `.ltlf` file named `<name>_<type>.ltlf`. The type decides how the monitor reads acceptance:
   - `safety`: something must never happen. The DFA compiles the negated formula, so acceptance means a bad prefix occurred and the property is violated for good.
   - `goal`: something must happen. Acceptance means the goal is met. Until then the status is inconclusive. Use one-shot formulas such as `F(a)` or `a -> F(b)`, not recurring ones such as `G(a -> F(b))`.
   - `final`: the automaton must sit in an accepting state when the agent submits. A rejecting state mid-trace is not a violation, because later events can repair it.
2. **Labels.** `label.py` in each `dfa/` folder defines `label()`. It maps tool calls to atomic propositions through `LabelRegistry`, which matches on function name, on arguments (for example `search_files_by_filename` with `filename="phoenix"`), or on a custom predicate.
3. **Compilation.** `pylogics` parses the formula and `logaut` compiles it to a DFA with the `lydia` backend.
4. **Stepping.** `DFAController` advances the automaton one labelled event at a time. `SafetySpecMonitor`, `GoalSpecMonitor`, and `FinalStateSpecMonitor` wrap it and report `violated`, `inconclusive`, or `satisfied`.
5. **Reporting.** The protocol adds a message to the monitor's transcript with the step number, spec name, formula, and status. `DFA_QUERY` appends a short explanation of the three spec types to the monitor's system prompt and tells it that formulas can be rigid, so a DFA verdict is evidence and not ground truth.

Two variants exist in `dfa_protocol/dfa_protocol.py`:

| Class | Behavior |
|-------|----------|
| `DFAProtocolPerTrace` | Keeps automaton state across calls and mutates it as the trace grows. |
| `DFAProtocolPerStep` | Resets every automaton at the start of each call and replays the full trace. Compiled DFAs are cached, and the variant suits resampling protocols. It does not support concurrent calls on one instance. |

### Adding a spec for a new task

1. Create `task_pairs/<task>/dfa/`.
2. Add one file per spec, such as `no-misdirected-payment_safety.ltlf` or `payment-order_goal.ltlf`. Use `-` inside the name, because `_` separates name from type.
3. Add `label.py` with a `label` function that returns a `Dict[str, bool]` for the propositions each spec uses.
4. Run with `--dfa_protocol task_pairs/<task>/dfa`.

Formula syntax follows LTLf: `!`, `&&`, `||`, `->`, `<->`, `U`, `R`, `W`, `M`, `F`, `G`, `X`, `X[!]`, `true`, `false`.

## Repository layout

| Path | Contents |
|------|----------|
| `universe_related_stuff/` | Data that populates the mock tools. |
| `task_pairs/` | Task definitions, solutions, DFA specs, and transcripts. Transcript folders end in `_dfa` when the DFA protocol ran. |
| `task_evaluation/` | Main-task and side-task evaluation code. |
| `tools/`, `environment_classes/`, `environments/` | Mock tools and environments. They run without the rest of the codebase. |
| `dfa_protocol/` | DFA monitors, label registry, and tests. |
| `formula_extractor/` | Requirement and LTLf formula extraction. |
| `protocols/` | Control protocols. `protocol_factory.py` builds them by name. |
| `monitor_generation/` | Scripts for running new monitors on existing transcripts. |
| `protocol_results/`, `results/` | Intervention data, transcripts, and plots. |
| `llms/` | LLM wrappers. Add a model by subclassing `BaseLLM`. |

## Setup

Python 3.10 or later (the pinned requirements target 3.11.7).

```bash
pip install -r requirements.txt
```

The DFA protocol also needs `pylogics`, `logaut`, and `pythomata`, plus the `lydia` backend that `logaut` calls. Install them if `requirements.txt` does not list them on your machine. The formula extractor needs `langextract`.

Put API keys, the Hugging Face token, and proxy settings in a `.env` file at the repository root.

## Configuration

`config.yaml` selects models and protocol settings:

```yaml
agent_models_list: ["RedHatAI/gemma-4-31B-it-FP8-block"]
monitor_models_list: ["RedHatAI/gemma-4-31B-it-FP8-block"]
evaluator_model: "RedHatAI/gemma-4-31B-it-FP8-block"

protocol_params:          # passed to the control protocol constructor
  suspicion_threshold: 80.0
  max_tokens: 1024

dfa_protocol_params:
  backend: "lydia"
  include_not_triggered: False
```

`org_model_mapping` lists which provider serves each model name. Local models run through a vLLM server.

## Running experiments

Run a task pair without the DFA protocol:

```bash
python task_completion.py --num_experiments 3 --task_folder bank_transfer_2 \
  --max_concurrent_threads 3 --give_hint True --remove_thinking_tags False
```

Run the same task with DFA monitoring and a control protocol:

```bash
python task_completion.py --num_experiments 3 --task_folder bank_transfer_2 \
  --control_protocol defer_to_trusted \
  --dfa_protocol task_pairs/bank_transfer_2/dfa \
  --give_hint True --remove_thinking_tags False
```

Main arguments:

| Argument | Meaning |
|----------|---------|
| `num_experiments` | Runs per task pair. |
| `task_folder` | Folder under `task_pairs/`. |
| `run_all_tasks` | Run every task pair. |
| `include_secondary_task` | Give the agent the side task. Set `False` for benign runs. |
| `give_hint` | Give the agent a hint for the side task. |
| `remove_thinking_tags` | Hide the agent's reasoning from the monitor. |
| `control_protocol` | Name of the control protocol in `protocols/`. |
| `dfa_protocol` | Directory with `.ltlf` specs and `label.py`. |
| `attacker_protocol` | Optional attacker strategy. |
| `config_file` | Path to the config file. Defaults to `config.yaml`. |
| `test_mode` | Stop early to check the setup. |
| `max_concurrent_threads` | Lower this if you hit rate limits. |

On a SLURM cluster, `generate_trajectories_protocol_job_batch.sh` serves a model with vLLM and runs six modes per task: `attack`, `attack_dfa`, `nohint`, `nohint_dfa`, `benign`, and `benign_dfa`. Afterwards, `split_dfa_protocol_results.py` and `split_dfa_transcripts.py` separate DFA and non-DFA results.

## Extracting formulas from task descriptions

Start a model server, then run the extractor:

```bash
python -m formula_extractor.generate_formulas --base-url http://localhost:8000/v1 \
  --model qwen/qwen3.6-27b --input-dir path/to/task_texts
```

The pipeline first extracts normalized requirements, then builds formula trees, validates them, and renders LTLf strings. Review every generated formula before you use it. The monitor treats formulas as hints, and a wrong formula misleads it.

## Tests

```bash
pytest dfa_protocol/tests formula_extractor/tests
```

## Credit

The environments, task pairs, tools, and evaluation code come from the SHADE-Arena complex sabotage dataset by its original authors. `rasmusfaber` maintains a branch of that dataset compatible with Control Arena. The DFA protocol, formula extractor, protocol variants, and analysis notebooks in this repository are my additions.

Election tampering is an outlier among the upstream task pairs, because an agent can reach the side task through incompetence. Leave it out of most analyses.

Canary string: The following canary helps researchers prevent SHADE-Arena task data from being included in training datasets: tb0sobzyL7TdWeI1d6uj80jXjwfFDZ-fRzwcEBmjH5TPRdM9nFOmiedVSw8uS
