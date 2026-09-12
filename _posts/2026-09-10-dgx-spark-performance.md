---
title: "Tuning a 26B MoE agent on a DGX Spark to over 100 t/s"
subtitle: "Six configuration changes, each measured the same way"
description: "Tuning llama.cpp on an NVIDIA DGX Spark to get 100+ tokens per second out of a 26B sparse MoE agent."
background: "/img/bg-post.svg"
---

**How much can you get out of a DGX Spark before deciding it is not enough to run an agent on —
and why chasing tokens per second should not always be the goal?**

The machine and the workload are [on the About page]({{ site.baseurl }}/about/): a DGX Spark (GB10) with 128 GB of
unified memory and no separate VRAM, serving an infrastructure agent. **Bandwidth is the only
constraint that matters here**, and every number below is downstream of it.

It started at roughly **45 t/s**. It now streams **over 100 t/s** on the turns that make up most of
the work, spikes to **138 t/s** on a single prompt, and reaches roughly **280 t/s** in aggregate
across sixteen concurrent streams. Two phases got it there: cutting the context a turn actually
needs, then six changes to the runtime — one flag or one file at a time, each measured before the
next.

**Real context sizes and distinct prompts are what make these numbers different — and worth far
more.** The figures published online for this hardware, as far as I could find them, come from one
fixed prompt at a short static context, with concurrency measured on that same prompt fired N times
at once — which measures how cheaply one request can be duplicated, not how the box handles N
different ones. Measuring the way the agent actually runs makes every number here smaller, and it
is why they predicted production.

**This is not a "add these five flags and you get 100 t/s" post**, because no such answer exists.
What to change depends on what you run and what you run it for. Here it is agentic work with a mix
of small and medium contexts, where a sparse MoE in the 26–35B class fits the machine with room to
spare, and where the levers that paid were **packaging, speculative decoding, cache precision and
parallel slots**. Your workload may hand you a different set. What should transfer is the method:
what each number means, how to measure it, and why a figure quoted without its context length is
not a measurement. With that, you should be able to reach something similar here — or better.

Nothing below is a guess. Every figure comes from `llama-bench` with error bars, from the server's
own journal under real traffic, or — for the bus and for where a pass spends its time — from a
buffer benchmark and a profiler. Each one is quoted with the metric it came from and the context
length it was taken at.

## One configuration, three honest numbers

Before any of the tuning, a caveat that governs how every figure here should be read — and that
explains why published benchmarks and production experience so often disagree.

The same server, the same model, the same flags, measured three ways:

| what was measured | result | n |
| --- | --- | --- |
| single prompt on an idle box, with speculation | **105–138 t/s** | 3 prompts |
| real agent turns under 8k context | **101.4 t/s** streaming median | 348 samples |
| decode at 64k context | **55.0 t/s** | ±0.09 |

*Row 2 is `tg_3s`, the streaming rate — see [Methodology](#methodology-how-the-numbers-were-taken).
The same turns measured as a per-request average (`eval time`) give 90.7 t/s, n=59. Two metrics
of one state, not a before and after.*

**Nothing is inconsistent here.** A 2.5× spread across one configuration comes almost entirely from
**context length**, and that is the variable most published figures leave unstated.

This matters for reading anyone's numbers, including these. A widely quoted figure for this model
on this hardware is **108.78 t/s** under vLLM with speculation, taken single-stream on a server
capped at 4,096 tokens of context. That is not my workload, and on its own it would not have made
the agent usable — but it is what started this, because it said the hardware had more in it than
the 45 t/s I was getting. The comparable measurement here, taken the same way, is **105–138
t/s**; the 64k figure of 55.0 is not a worse result, it is a different question, and it is the one
nobody publishes.

**Which number describes my agent?** Mostly the middle one. Event processing and rule execution
run under 8k context, and a plain status question is a few thousand tokens. The 64k case is real —
long log investigations reach it — but it is the tail, not the day. That is why the tuning below
targets both ends and reports both.

---

## Methodology: how the numbers were taken

The tuning runs in **six stages**, one change at a time, each measured before the next was made:

- **Stage 1, baseline** — Google's QAT release, `Q4_0`, as shipped.
- **Stage 2, packaging** — the same quantization format from a different packer.
- **Stage 3, speculation** — multi-token prediction, drafting four tokens per pass.
- **Stage 4, parallelism** — scaling one box to concurrent work, and what it costs.
- **Stage 5, cache precision** — `q8_0` → `f16` on the KV cache.
- **Stage 6, generalisation** — the same sweep against two other vendors' models.

Then one number was still missing, so the tuning stops and a profiler takes over.

The rest of this section is the setup behind them: where the evidence comes from, which three
throughput figures the server reports and what each of them answers, the tools, the build, and the
one unit everything is measured against.

### The journal — where the evidence comes from

Most of the figures below are quoted from **the journal**. `llama-server` runs as a systemd user
unit, so everything it writes to stdout is captured by systemd's log store and read back with
`journalctl`:

```
journalctl --user -u llm-server -f          # follow live
journalctl --user -u llm-server -S 09:29   # a window
```

At `-lv 3` the server emits a `print_timing` line for **every request it completes**. That is the
whole appeal: it is the server reporting on real traffic, continuously, with no benchmark harness
in the path and nothing to set up. Eight minutes of ordinary agent use produces a few hundred
labelled measurements for free.

```
Sep 10 09:29:38 gb10 start-llm-poc.sh[592816]: 6.35.144.849 I slot print_timing: id  1 | task 0 | n_gen =    286, tg =  94.36 t/s, tg_3s =  94.68 t/s
Sep 10 09:29:39 gb10 start-llm-poc.sh[592816]: 6.35.657.294 I slot print_timing: id  1 | task 0 | prompt eval time =    4637.24 ms / 13516 tokens (    0.34 ms per token,  2914.66 tokens per second)
Sep 10 09:29:39 gb10 start-llm-poc.sh[592816]: 6.35.657.297 I slot print_timing: id  1 | task 0 |        eval time =    3532.91 ms /   334 tokens (   10.61 ms per token,    94.26 tokens per second)
Sep 10 09:29:41 gb10 start-llm-poc.sh[592816]: 6.38.266.322 I slot print_timing: id  1 | task 112 | prompt eval time =     280.09 ms /    93 tokens (    3.01 ms per token,   332.04 tokens per second)
Sep 10 09:29:41 gb10 start-llm-poc.sh[592816]: 6.38.266.326 I slot print_timing: id  1 | task 112 |        eval time =    1730.32 ms /   156 tokens (   11.16 ms per token,    89.58 tokens per second)
```

Two fields matter when reading these. **`id`** is the slot, one of the `-np` parallel slots.
**`task`** is the request, and it ties the lines together: one task emits a `prompt eval` line and
an `eval time` line when it finishes, plus an `n_gen` line whenever the server samples a generation
still in flight.

The excerpt is one turn of real work — task 0 ingests a 13,516-token prompt, task 112 is the next
round of the same conversation and ingests only the 93 new tokens of tool output. Which is where
the three numbers come in.

### Three numbers, three questions

`llama-server` at `-lv 3` reports three throughput numbers per request. They answer different
questions, and treating them as interchangeable produces wrong conclusions.

| metric | what it is | the question it answers |
| --- | --- | --- |
| **prompt eval t/s** | prefill — ingesting the prompt | how long before the first token appears |
| **eval time t/s** | decode, averaged over one whole generation, reported at the end | which configuration is faster |
| **n_gen `tg` / `tg_3s`** | decode sampled *during* generation; `tg` running, `tg_3s` a trailing 3-second window | what streaming actually feels like |

Each has a trap.

**prompt eval t/s is meaningless without its token count.** The rate scales with how much there is
to process, because a small batch never amortizes the weight read. Four tasks from the same window
as the excerpt above:

```
task    0  prompt  13516 tokens @  2915 t/s
task  112  prompt     93 tokens @   332 t/s
task  237  prompt     76 tokens @   328 t/s
task  638  prompt   1083 tokens @  1918 t/s
```

Those are not four speeds. They are one speed over four batch sizes. And the token counts show
something else: **prompt caching means a turn pays full prefill once.** Round 1 ingests 13,516
tokens; later rounds process only the new tool output.

**eval time t/s is a per-request average**, folding in the ramp-up and reporting one figure however
long the generation ran. Best for comparing configurations, because each request contributes
equally.

**`tg_3s` is the closest thing to perceived speed**, emitted several times during a long
generation — so long rounds contribute more samples than short ones. A feature when you want to
know how it feels, a bias when you want to compare configs.

### Tools

**`llama-bench` for anything a flag controls.** It ships with llama.cpp: `-d` prefills to a context
depth before measuring generation, `-r` repeats and reports a standard deviation, comma-separated
values sweep a parameter, and `pp` and `tg` print as separate rows so the two can never be
conflated. It stamps the build hash on its output.

It cannot do speculation — there are no draft-model flags — so **MTP figures come from the server
journal instead**. That is the dividing line used throughout: `llama-bench` for quantization, cache
type, depth, batch and threads; the journal for MTP, the chat template, and real turns.

**`nsys` for the one question a flag cannot answer**, at the end: where the time goes inside a pass.
Nsight Systems traces CUDA calls and kernels against the host thread that issues them, which is what
separates "the GPU is slow" from "the GPU is idle waiting for the CPU". Nothing above needed it;
[the last unexplained number](#where-the-engines-20-points-went) did.

### The build

Every figure here comes from one binary, and on this hardware the build configuration matters as
much as the runtime flags. Reconstructed from the CMake cache — the flags are exact, the line is
assembled from them:

```sh
cmake -B build \
  -DCMAKE_BUILD_TYPE=Release \
  -DGGML_CUDA=ON \
  -DCMAKE_CUDA_ARCHITECTURES=121a-real \
  -DGGML_CUDA_FA=ON -DGGML_CUDA_FA_ALL_QUANTS=ON \
  -DGGML_CUDA_GRAPHS=ON \
  -DGGML_CPU_ARM_ARCH="armv9.2-a+dotprod+fp16+i8mm+bf16+sve2" \
  -DGGML_CPU_REPACK=ON \
  -DCMAKE_C_COMPILER=gcc-14 -DCMAKE_CXX_COMPILER=g++-14
cmake --build build --config Release -j
```

| | |
| --- | --- |
| llama.cpp | `67672dc5b`, tag `b10850-1`, build **10851** |
| CUDA | 13.0, `V13.0.88` |
| compiler | gcc/g++ 14.2.0 |
| BLAS | off — CUDA handles the matmuls |

Three of those are specific to this machine rather than defaults.

**`CMAKE_CUDA_ARCHITECTURES=121a-real`** is the one to get right. GB10 is compute capability 12.1;
the `a` suffix enables the architecture-specific instructions Blackwell adds, and `-real` emits
only the real target instead of also carrying PTX for JIT. Build for a generic architecture and the
fast paths are simply not compiled in — the binary works and is slower, with nothing in the logs to
say why.

**`GGML_CPU_ARM_ARCH=armv9.2-a+…+sve2`** targets the Cortex-X925/A725 cores rather than a baseline
ARMv8, which matters for the CPU-side work around the GPU kernels.

**`GGML_CUDA_FA_ALL_QUANTS=ON`** compiles flash-attention kernels for every quantized KV type, not
just the common ones. Every stage below runs `-fa 1`, and Stage 5 compares KV cache types directly
— without this, some of those combinations would fall back to a slower path and the comparison
would measure the build rather than the format.

Every benchmark below ran with **all services stopped** — two large-context servers resident on one
128 GB box change each other's numbers. The one exception is the bus benchmark in the next section,
which turns out to need the opposite and says why.

### The unit everything is measured against

Decode reads weights across the memory bus, so the bus is the limit. Both halves of that were
measured rather than assumed.

**What the bus delivers**, from a buffer benchmark with no model involved:

| operation | GB/s |
| --- | --- |
| read-only (reduction) | **~250** |
| `copy` (read + write) | ~230 |
| triad (2 read + 1 write) | ~230 |

*4 GiB buffers, best of twelve runs, medians within a fraction of a percent of best. Read-only is
the figure that matters — decode reads weights rather than copying them — at roughly **250 GB/s,
about 90% of the 273 GB/s spec sheet**.*

**This is the one benchmark that must not be run on an empty machine.** Read-only bandwidth here
moves by around 8% with how much memory is already allocated: with nothing resident this box reads
about 240 GB/s, with tens of GiB resident about 250–260. It is not contention — the effect
reproduces against a process that only allocates and sleeps, running no kernels at all — and power
draw and SM clock are unchanged, so it is not frequency scaling either. Most likely it is how the
benchmark's own buffers get backed once the machine is full, but that part is a hypothesis; the
effect itself reverses on demand.

Decode always runs with the model resident — which is what "idle box" means everywhere else in this
post: no competing services, but the weights loaded. So ~250 is what this machine really offers a
running model, and measuring the bus on a genuinely empty one understates it. Expect different
absolute numbers on other hardware; the direction and the rough size are what transfers.

**What a token costs**, from the GGUF header rather than the "A4B" label:

```
  file total 13.26 GiB
    experts (sparse)         11.96 GiB
    attention (always)        0.58 GiB
    embeddings/output         0.39 GiB
    dense ffn (always)        0.32 GiB

  per token, with 8/128 experts routed:
    always-active           1.29 GiB   (63% of the read)
    routed experts          0.75 GiB
    PER FORWARD PASS        2.04 GiB
```

Two things fall out. The always-active path is **63% of what a token reads** — at batch 1 the
sparse experts are the *minority* component. And the whole model of decode becomes:

```
bytes per pass  =  2.04 GiB (weights)  +  KV × context
passes/second   =  achievable bandwidth / bytes per pass
throughput      =  passes/second × tokens retired per pass
```

Only the last factor can be moved. Bandwidth is not yours to tune and the weights are fixed, so
every stage below is an attempt to raise tokens-per-pass or reduce bytes-per-pass.

---

## The stages

In the order they were made. Each opens with what it won or did not, then gives its configuration
and its evidence.

The absolute numbers below are this box on these days. On yours they will differ — quite possibly
upward, since a good deal of what made these slow was mine to fix. What should carry across is the
direction of each change and roughly what it was worth.

### Stage 1 — the baseline: `google/gemma-4-26B-A4B-it-qat-q4_0`

**Not a win — the reference.** 77.92 t/s at zero context, 35.28 at 64k, and a real-turn median of
50.2 with 6% of requests below 40 t/s. Every later number is measured against these.

Google's QAT release, quantized to Q4_0 by the people who trained it.

```sh
MODEL_NAME=google/gemma-4-26B-A4B-it-qat-q4_0-gguf:Q4_0

llama-server \
  -hf ${MODEL_NAME} -lv 3 \
  -ngl 999 -fa 1 -c 200000 -np 1 -ub 2048 --no-mmap \
  -ctk q8_0 -ctv q8_0 --no-mmproj -t 10 --jinja \
  --host 0.0.0.0 --port 30000
```

**llama-bench**

| depth | prefill t/s | decode t/s |
| --- | --- | --- |
| 0 | 3060.05 ± 119.05 | 77.92 ± 0.22 |
| 4,096 | 2893.03 ± 51.50 | 71.65 ± 0.20 |
| 16,384 | 2506.60 ± 39.42 | 58.61 ± 0.11 |
| 65,536 | 1634.02 ± 28.96 | **35.28 ± 0.04** |

*`-p 512 -n 128 -r 3 -fa on -ngl 999 -t 10`, build `67672dc5b (10851)`, idle box.*

**Journal, real turns**

Median **50.2 t/s** over 650 requests, p10 43.4, and **6% of requests below 40 t/s**. That tail is
the part a person notices.

The gap between 77.92 on a synthetic prompt and 50.2 on real traffic is not a discrepancy — real
turns carry long context and reasoning-heavy output. The two numbers answer different questions,
and the rest of this article keeps them apart.

### Stage 2 — the same model, a different packer

**A win for free: +8.1% at zero context, +4.4% at 64k, for changing who packed the file.**

`unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL`. Same weights, same quantization format, and
**every other flag identical**, including `-ctk q8_0`.

```sh
MODEL_NAME=unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL
# flags unchanged from Stage 1
```

The filename says Q4_K. The GGUF header says otherwise:

```
general.name = "Gemma-4 26B-A4B IT (smart Q4_0, QAT-lossless)"
  F32     392 tensors
  Q4_0    266 tensors      <- not one Q4_K tensor in the file
```

**It is Q4_0 throughout**, with the `UD-…_XL` name carried over from unsloth's Dynamic scheme.
Google's own file is 265 Q4_0 tensors plus one Q6_K. The two builds use the *same* format,
differing only in which tensors stay F32 and how the QAT weights were packed — so this stage is not
a quantization change at all, it is a packing change.

**llama-bench**

| depth | Stage 1 (google) | Stage 2 (unsloth) | gain |
| --- | --- | --- | --- |
| 0 | 77.92 | **84.24 ± 0.19** | +8.1% |
| 4,096 | 71.65 | **76.91 ± 0.24** | +7.3% |
| 16,384 | 58.61 | **62.51 ± 0.10** | +6.7% |
| 65,536 | 35.28 | **36.82 ± 0.07** | +4.4% |

*Both `-ctk q8_0 -ctv q8_0`, identical flags, same build, same box.*

Prefill is unchanged within noise (3060 vs 3084 at d0), and that is what identifies the cause:
this is a decode-path difference, and decode is where bytes-per-pass lives. The unsloth file is
13.26 GiB against google's 13.43 — slightly fewer bytes to read per token.

**The gain shrinks with depth**, from 8.1% to 4.4%, and that is the model working as described: at
depth the KV term grows while the weights term stays fixed, so a weights-side saving matters
proportionally less.

### Stage 3 — speculation: multi-token prediction

**The largest win on real traffic: the median turn goes 50.2 → 72.7 t/s, about 1.45×, and the slow
tail disappears entirely.**

If you cannot read fewer bytes, retire more tokens per read. MTP drafts several tokens and verifies
them in one forward pass.

```sh
MODEL_NAME=unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL
DRAFT_NAME=unsloth/gemma-4-26B-A4B-it-qat-GGUF:Q8_0   # mtp-gemma-4-26B-A4B-it.gguf, ~462 MB

llama-server \
  -hf ${MODEL_NAME} -hfd ${DRAFT_NAME} -lv 3 \
  --spec-type draft-mtp --spec-draft-n-max 4 \
  -ngl 999 -fa 1 -c 200000 -np 1 -ub 2048 --no-mmap \
  -ctk q8_0 -ctv q8_0 --no-mmproj -t 10 --jinja \
  --host 0.0.0.0 --port 30001
```

Two flags do the work: `-hfd` fetches the draft head from the same repo as the weights, and
`--spec-type draft-mtp` turns speculation on.

**`llama-bench` cannot measure this** — no draft-model support — so the evidence is the journal.

**Journal, real turns**

| | median | p10 | requests under 40 t/s |
| --- | --- | --- | --- |
| Stage 2 config | 50.2 t/s | 43.4 | 6% of 650 |
| Stage 3 (+MTP) | **72.7 t/s** | **63.8** | **0 of 35** |

Two consecutive rounds of one live turn:

```
id 1 | task   0 | eval time = 3532.91 ms / 334 tokens (10.61 ms/tok, 94.26 t/s)
id 1 | task   0 | draft acceptance = 0.57108 ( 233 accepted / 408 generated), mean len = 3.28
id 1 | task 112 | eval time = 1730.32 ms / 156 tokens (11.16 ms/tok, 89.58 t/s)
id 1 | task 112 | draft acceptance = 0.54000 ( 108 accepted / 200 generated), mean len = 3.16
```

**~1.45× on the median turn, and the slow tail disappears entirely.** The floor moving matters more
than the median — from the outside it reads as "the bot got consistent" rather than "the bot got
faster".

`draft acceptance` is the number to watch. It tracks how predictable the output is — around 0.9 on
tool-call JSON, around 0.5 on prose — so speculation pays most exactly where an agent spends its
tokens.

**How far speculation pays.** Sweeping `--spec-draft-n-max` on a real replayed turn:

| `n-max` | decode t/s | acceptance | mean len | passes/s |
| --- | --- | --- | --- | --- |
| 2 | 77.4 | 0.872 | 2.74 | 28.2 |
| **4** | **85.3** | 0.701 | 3.78 | 22.6 |
| 6 | 84.9 | 0.586 | 4.46 | 19.0 |
| 8 | 81.6 | 0.502 | 4.98 | 16.4 |
| 12 | 78.4 | 0.411 | 5.86 | 13.4 |

```
n-max  4  | draft acceptance = 0.70064 ( 220 accepted /  314 generated), mean len = 3.78
n-max 12  | draft acceptance = 0.41060 ( 248 accepted /  604 generated), mean len = 5.86
```

Read the `generated` column: drafting twelve ahead produces 604 candidates to keep 248, against 314
for 220 at four. Acceptance falls as the draft head guesses further ahead, tokens-per-pass rises,
and the pass rate falls almost exactly in step — so the product peaks at **4** and decays after.
The default was already optimal; the sweep bought the knowledge rather than the throughput.

**One caveat worth knowing: MTP blinds logprobs.** 248 of 250 tokens return `logprob` exactly 0.0
with an empty `top_logprobs`, against 0 blanks without speculation — draft-accepted tokens are
never scored. Anything downstream consuming logprobs breaks silently.

### Stage 4 — parallelism: two slots

**A capacity win rather than a speed one.** Single-stream throughput is unchanged; what the box
gains is the ability to serve concurrent work — two slots here, so chat and automation stop waiting
for each other, and up to sixteen if what you want is aggregate rather than latency. The cost is
memory: roughly 8 GB of KV per slot.

The agent has two entry paths that can fire together: a person's chat turn, and a rule-triggered
automation run. At one slot they serialize, one waiting out the whole of the other.

```sh
llama-server \
  ... \
  -c 400000 -np 2 \
  ...
```

**The trap is `-c`.** llama.cpp splits it across slots, so `-np 2` at `-c 200000` gives each slot
100,000 — and the largest real turn observed here was 90,959 tokens. `-c 400000` keeps 200,192 per
slot.

**Does an idle slot cost throughput?** Single-stream, second slot empty:

| prompt | `-np 1` | `-np 2` | ratio |
| --- | --- | --- | --- |
| prose | 106.8 | 102.5 | 0.96× |
| json | 135.0 | 142.0 | 1.05× |
| list | 115.9 | 121.9 | 1.05× |

Ratios scatter either side of 1.00 with no direction — noise, not penalty. **llama.cpp batches only
slots that have work**, so an idle slot does not slow the busy one down.

**It is not free, though — it is paid for in memory and in context.** The slot's KV reservation is
allocated whether or not anything is using it, about 8 GB here, and `-c` is divided rather than
shared, so each slot's usable context is `-c / -np`. That is the real price of the second slot:
not tokens per second, but roughly 8 GB of unified memory and the obligation to double `-c` to
keep the per-slot ceiling where it was.

**What concurrency actually buys.** The obvious way to measure this is to fire N copies of the
same request. That measurement is wrong, and the size of the error is the interesting part — so
both are here, N streams of the *same* prompt against N streams of *different* prompts:

| streams | identical prompts | distinct prompts | per stream, distinct |
| --- | --- | --- | --- |
| 1 | 103.5 | 103.1 | 103.1 |
| 4 | 236.0 | 166.7 | 41.7 |
| 8 | 322.0 | 222.3 | 27.8 |
| 16 | 411.3 | **280.2** | **17.5** |

*One server at `-np 16 -c 262144` (16,384 per slot) with `f16` KV and MTP, 300 tokens per request,
median of three runs at each point. The distinct column uses sixteen unrelated subjects — bread,
locomotives, coral, Russian novels — chosen to have nothing in common.*

**Identical prompts overstate aggregate throughput by 47%.** At one stream the two agree to within
0.4%, so this is not prompt caching; it is what happens once several sequences run together. At
temperature 0, sixteen copies of one prompt generate the same tokens in lockstep, so every forward
pass activates the **same 8 of 128 experts** for all sixteen sequences. The expert weights are read
once and shared across the whole batch. Real users do not do that.

The journal shows the difference plainly. Identical prompts, slots finishing within *milliseconds*
of each other at the same rate:

```
id  1 | task 1346 | eval time = 11905.15 ms / 300 tokens (39.82 ms per token, 25.12 t/s)
id  2 | task 1347 | eval time = 11904.95 ms / 300 tokens (39.82 ms per token, 25.12 t/s)
id  3 | task 1348 | eval time = 11904.73 ms / 300 tokens (39.82 ms per token, 25.12 t/s)
id 11 | task 1356 | eval time = 11896.94 ms / 300 tokens (39.79 ms per token, 25.13 t/s)
```

Distinct prompts, the same sixteen slots — the lockstep is gone and every slot is slower:

```
id  4 | task 2657 | eval time = 15137.00 ms / 300 tokens (50.63 ms per token, 19.75 t/s)
id 11 | task 2664 | eval time = 15342.81 ms / 300 tokens (51.31 ms per token, 19.49 t/s)
id  9 | task 2653 | eval time = 15998.16 ms / 300 tokens (53.51 ms per token, 18.69 t/s)
id 13 | task 2663 | eval time = 16643.44 ms / 300 tokens (55.66 ms per token, 17.97 t/s)
```

Divergent sequences route to different experts, so bytes per pass climb with the number of streams
instead of staying flat. **A synthetic benchmark hides that by construction**, and on a sparse MoE
it is worth a third of the headline.

**Treat 280 as an estimate rather than a measurement.** The distinct-prompt run has two variables
still uncontrolled: streams that finish early leave slots idle, and MTP draft acceptance varies with
subject matter. Both push the figure down, so the honest reading is *somewhere between the two
columns, nearer the right-hand one*.

What does not depend on that resolution is the shape. **The aggregate flattens**, and **the
per-stream rate collapses** — 103 t/s alone, under 20 with sixteen running. Aggregate throughput is
capacity, not speed, and beyond a handful of slots it is capacity bought entirely at the expense of
the person waiting.

**For my workload the aggregate is irrelevant and the per-stream figure is not.** One person waits
at a time. Two slots is the right number because it stops automation and chat blocking each other
for free; eight would trade a single turn's speed for capacity nobody uses.

### Stage 5 — KV cache precision: `q8_0` → `f16`

**The largest single win in this article: +49.5% at 64k context — by moving twice the bytes.**

`-ctk q8_0 -ctv q8_0` had been in the configuration from the beginning, on the obvious reasoning:
half the bytes, and it is what makes a 200K context affordable. Since the KV term dominates at
depth, halving it ought to help most exactly where help is needed.

```sh
llama-server \
  ... \
  -ctk f16 -ctv f16 \
  ...
```

**It does the opposite.** Four cache-type combinations across four depths:

| depth | `f16`/`f16` | `f16`/`q8_0` | `q8_0`/`f16` | `q8_0`/`q8_0` | f16 gain |
| --- | --- | --- | --- | --- | --- |
| 0 | **87.92** | 85.75 | 85.43 | 84.00 | +4.7% |
| 4,096 | **78.93** | 77.68 | 77.27 | 76.84 | +2.7% |
| 16,384 | **72.65** | 67.33 | 66.96 | 62.21 | **+16.8%** |
| 65,536 | **54.96** | 43.97 | 43.87 | 36.77 | **+49.5%** |

*tg128, `-r 3`, ±0.30 or better; the d65536 column is ±0.10.*

**f16 moves ~1.9× more bytes and wins by half at depth.** That is a factor of four in the wrong
direction for anything bandwidth explains. The q8_0 penalty was never bytes — it is
**dequantization**: every cached key and value is unpacked on every generated token, and past
roughly 10k tokens that compute cost swamps the bandwidth it saves. Below 4k the four
configurations sit within 5% of each other, which is the same statement from the other end: with an
almost-empty cache there is nothing to unpack.

A matched pair from the journal confirms it outside the benchmark — same task id, same
68,827-token prompt, same 200 tokens generated:

```
q8_0   task 1040 | prompt eval time = 28883.32 ms / 68827 tokens (0.42 ms/tok, 2382.93 t/s)
q8_0   task 1040 |        eval time =  5668.50 ms /   200 tokens (28.48 ms/tok,   35.11 t/s)

f16    task 1040 | prompt eval time = 27666.58 ms / 68827 tokens (0.40 ms/tok, 2487.73 t/s)
f16    task 1040 |        eval time =  4020.66 ms /   200 tokens (20.20 ms/tok,   49.49 t/s)
```

Prefill within 4%, decode differing by 41%. Whatever f16 is doing, it does it during generation,
not ingestion.

**Quantizing K and V costs the same.** At d65536, `f16`/`q8_0` gives 43.97 and `q8_0`/`f16` gives
43.87 — 0.2% apart on ±0.10 error bars. Either half alone costs 20%; both cost 33%. The asymmetric
configurations are the worst of both — almost all the speed given up for half the memory saved.
The common intuition that keys are more quantization-sensitive than values is a claim about
**quality**, and it does not transfer to the performance axis: the cost is per-KV-access
dequantization, and K and V are accessed equally.

**Journal, real traffic**, splitting at the switch:

| context | q8_0 | n | f16 | n | gain |
| --- | --- | --- | --- | --- | --- |
| <3k | 99.0 | 56 | 89.5 | 23 | −10% |
| 3–10k | 78.5 | 2 | 92.6 | 2 | +18% |
| 10–40k | 70.8 | 8 | **85.9** | 7 | **+21%** |
| >40k | 39.6 | 2 | **61.3** | 4 | **+55%** |

*Buckets outside `<3k` hold single-digit samples — direction, not magnitude. The −10% at `<3k` is
noise; the controlled sweep had the two level there, and there is no mechanism by which f16 is
slower on a nearly-empty cache.*

On the streaming metric the same period gives median `tg` **68.3 → 86.2** and `tg_3s`
**69.3 → 95.5**, with the floor moving from **31.3 to 56.8 t/s**. The floor is why the agent feels
different to use.

**The cost is memory, not throughput.** f16 KV is ~1.9× larger, so a 400K allocation goes from
roughly 16 GB to 31 GB. On a 128 GB box that is affordable — and the honest framing is that **KV
quantization buys context length and pays for it in long-context speed**, which is the opposite of
how it is usually described.

### Stage 6 — does any of this generalise?

**Not a win but a correction.** The Stage 5 result is not Gemma-specific: GLM pays 75% where Qwen
pays nothing, and what predicts it is attention design rather than vendor.

A win that large invites one question: is it a fact about llama.cpp, about this hardware, or about
**this model**? The test: run the same cache sweep
against other vendors' models of the same class — `unsloth/Qwen3.6-35B-A3B-MTP`, a sparse MoE at
Q4_K_XL, and `GLM-4.7-Flash` at Q4_K, a 30B-A3B MoE that llama.cpp loads under the `deepseek2`
architecture.

**llama-bench, Qwen3.6-35B-A3B**

| depth | `f16`/`f16` | `f16`/`q8_0` | `q8_0`/`f16` | `q8_0`/`q8_0` |
| --- | --- | --- | --- | --- |
| 0 | 68.03 ± 0.22 | 67.47 ± 0.23 | 67.34 ± 0.30 | 67.17 ± 0.15 |
| 16,384 | 61.56 ± 0.27 | 61.62 ± 0.16 | 61.43 ± 0.19 | 61.40 ± 0.14 |
| 65,536 | 48.46 ± 0.07 | 48.69 ± 0.14 | 48.27 ± 0.09 | 48.34 ± 0.06 |

**KV quantization costs Qwen nothing.** A 0.4% spread at d65536 against ±0.06–0.14 error bars —
indistinguishable. Where gemma-4 pays **+49.5%** for f16, Qwen pays **zero**.

That looked like a clean answer — the Stage 5 result is Gemma-specific — until the third model.

**llama-bench, GLM-4.7-Flash (30B-A3B, `deepseek2`)**

| depth | `f16` | `q8_0` | f16 advantage |
| --- | --- | --- | --- |
| 0 | 73.14 ± 0.12 | 71.33 ± 0.15 | +2.5% |
| 16,384 | 55.11 ± 0.13 | 45.43 ± 0.11 | +21.3% |
| 65,536 | **32.96 ± 0.02** | **18.81 ± 0.01** | **+75.2%** |

*Two columns rather than four: this architecture keeps one shared latent cache, so mixed `-ctk`/
`-ctv` types are rejected outright — `failed to create context`. The sweep that runs on the other
two models is not available here.*

**GLM pays more than Gemma does.** 75% at 64k against Gemma's 49.5%, and by the same shape — nothing
at zero context, growing with depth. So "Gemma-specific" was wrong. Two of three models pay
heavily, and Qwen is the exception rather than the rule.

**The mechanism survives the correction, and it is not about vendors.** What Gemma and GLM have in
common is a deliberately *small* KV cache. Gemma 4 interleaves 5:1 — 25 sliding-window layers
capped at 1,024 tokens, and only 5 global layers that grow with context, those given **2 KV heads
instead of 8**. Almost nothing accumulates per token.

GLM arrives at the same place by another route: `deepseek2`-style attention compresses keys and
values into a single low-rank latent, so what is cached per token is a fraction of a conventional
K and V. Qwen does neither and carries an ordinary, large cache.

A small cache is precisely the case where per-element dequantization *compute* dominates the KV
path instead of hiding beneath bandwidth. The same dequant work disappears into Qwen's larger
cache; Gemma's and GLM's are too small to hide it.

**So the rule is about attention design, not about the model.** Anyone applying "quantize the KV
cache, it saves bandwidth" will be right on models with a big conventional cache and badly wrong on
the ones engineered to have a small one — which is increasingly what new architectures are for. Two
models, two different mechanisms, the same 50–75% penalty.

**So give Gemma a bigger cache and the penalty should vanish.** That is the obvious objection, and
it is testable. Most of the cache shape is trained in — `key_length` 512, `key_length_swa` 256, a
per-layer `head_count_kv` array, a 1,024-token window — but `--swa-full` hands the sliding-window
layers a full-size cache instead of a ring, which is as close to Qwen's shape as this model gets.

| ~21k context | `q8_0` | `f16` | f16 advantage |
| --- | --- | --- | --- |
| default, ring SWA | 55.97 | **60.08** | +7.3% |
| `--swa-full` | **40.12** | 34.49 | −14.0% |

*`llama-server` rather than `llama-bench`, which has no SWA flag: one 21k-token prompt, 200 tokens
generated, `-c 32768`, everything else held. Not comparable with the tables above — the comparison
that matters is across each row.*

**The advantage reverses.** With a full-size cache `q8_0` becomes the faster choice, which is the
mechanism stated out loud: give the kernel enough KV to read and bandwidth dominates again, so
halving the bytes wins and the dequantization hides underneath it — exactly what happens on Qwen
without anyone asking for it.

It is still a bad trade, which is the useful half of the result. Both configurations lose heavily
for the privilege, so the fastest cell in that table is the one you started from. You can make
quantizing pay on this architecture, but only by making everything slower first. The small cache
is the feature; f16 is what the feature costs.

**GLM has no such lever at all**, and that is the sharper half. Gemma's small cache comes from
windowing, which is an allocation decision and therefore adjustable — badly, but adjustable. GLM's
comes from the weights: `deepseek2`-style attention projects K and V down into a low-rank latent
(`kv_lora_rank` 512 in this family), and those projections are trained at that size. There is no
ring to widen and no flag that widens it — llama.cpp does not build an SWA cache for the
`deepseek2` path at all. GLM pays its 75% and cannot opt out of it.

Gemma still wins the comparison outright: **54.96** at d65536 against Qwen's 48.46 and GLM's 32.96,
and **87.92** at zero context against 68.03 and 73.14 — from the smallest file of the three, 13.26
GiB against GLM's 16.98.

---

## The instrument panel lies

Three dials mislead, and all three were nearly taken at face value.

**"GPU utilization is 100%, so there is no headroom."** `nvidia-smi` utilization reports the
fraction of time at least one kernel is *resident* — not compute performed. A kernel stalled on
DRAM reads 84% while doing very little arithmetic.

**"Power caps around 45 W, so the GPU is not fully loaded."** True, and it means the opposite of
what it looks like. Same GPU, minutes apart:

| phase | GPU % | power | SM clock |
| --- | --- | --- | --- |
| idle | 0% | 12.2 W | 2405 MHz |
| **prefill** (47,616 tok) | 96% | **70.1 W** | 2509 MHz |
| **decode** (600 tok) | 84% | **44.8 W** | 2515 MHz |

*`nvidia-smi` sampled every 200 ms, medians over each request's window. A 47,616-token prompt with
`max_tokens: 1` isolates prefill; a 5-token prompt generating 600 isolates decode.*

The silicon draws **1.6× more power during prefill at the same clocks**. Decode is not leaving
performance unused — it is a workload that does not need the ALUs, because it is waiting on memory.
**Low power during decode is the signature of a memory-bound workload**, and exactly what should be
expected.

**"The profiler says the GPU is idle 90% of the time."** The worst of the three, because it arrives
wearing a profiler's authority. `nsys` defaults to `--cuda-graph-trace=graph`, which records that a
CUDA graph was launched and does not trace the kernels inside it — and llama.cpp runs decode almost
entirely inside graphs. One server decode, captured twice, reports **10% GPU busy at the default
granularity and 86% at `--cuda-graph-trace=node`**. The default is not wrong, it is answering a
different question, and its answer inverts the conclusion.

---

## Summary

Six stages, one change at a time:

| stage | change | decode @ d65536 | note |
| --- | --- | --- | --- |
| 1 | `google:Q4_0` baseline | ~35 | ~50 t/s median on real turns |
| 2 | → `unsloth:UD-Q4_K_XL` | ~37 | same Q4_0 format, better packing |
| 3 | + MTP (`draft-mtp`, n-max 4) | — | **~1.5× on real turns**, slow tail gone |
| 4 | + `-np 2 -c 400000` | — | capacity, not speed: ~8 GB KV per slot, scales to 16 streams |
| 5 | `-ctk/-ctv` → `f16` | **~55** | **about +50%** at depth |
| 6 | challenge vs Qwen, GLM | ~48 / ~33 | the Stage 5 win tracks attention design, not vendor |

**Roughly 35 → 55 t/s at 64k context**, plus a real-turn median that moved about 50 → 73 and a
sub-40 t/s tail that went from 6% of requests to none. Exact figures with their error bars are in
each stage above.

Where the machine now stands against its own limits:

```
bytes per pass  =  2.04 GiB + KV × context
achieved        =  2.04 GiB × 87.9 passes/s  =  193 GB/s
```

Everything on one baseline, the spec sheet, because that is the number a reader arrives with:

```
                                              of spec
  spec sheet                    273 GB/s        100%
  what the bus actually gives  ~250 GB/s         90%
  what the engine achieves      193 GB/s         70%
```

*87.9 is the measured zero-context decode rate of the final configuration, where the KV term is
zero and every pass retires one token, so passes per second and tokens per second are the same
number. Sizes here are **GiB** (2³⁰); rates are **GB/s** (10⁹), which is what the spec sheet
quotes.*

**You will not get the number on the box, and roughly 70% of it is a fair expectation.** Two layers
take the difference, and neither is a defect:

**About 10 points go to the machine.** 273 GB/s is a peak the memory system does not sustain to a
running program, and what it does sustain depends on conditions outside the model entirely — kernel
allocation, how the buffers end up backed, how full the box is. Those conditions are also why the
figure is a range rather than a constant, which is a separate point from the shortfall itself. No
amount of engine tuning reaches any of it, and a benchmark that appears to is usually measuring
something other than the bus.

**About 20 points go to llama.cpp.** This is the part that is a property of the inference engine
rather than the hardware, which makes it the only part worth attacking — and it was the largest
number left on this box, so it got profiled rather than left as a claim.

---

## Where the engine's 20 points went

**Of the engine's 20 points, roughly three in four are the GPU computing more slowly than the bus
could feed it, and the rest is the GPU sitting idle between tokens.**

That split comes from Nsight Systems, profiling the same benchmark the 193 GB/s came from. It has to
be run at node graph granularity — [as above](#the-instrument-panel-lies), the default answers a
different question and reports the GPU as almost entirely idle.

The smaller share, the idle, is the easier one to understand and turned out to be the harder one to
spend. Decode alternates: the GPU computes a token, then a single CPU thread samples it, checks the
speculative draft and sets up the next pass, while the GPU waits. **The core pinned at 100% during
all this is not working — it is spinning inside a CUDA wait**, which looks identical to work in
`top` and is why that thread shows almost no system time. Nothing is queued behind it.

Two ways to reclaim that idle, both measured, neither worth having:

**A second slot does not overlap it.** llama.cpp batches two slots into one forward pass rather than
running two pipelines, so the host work per pass goes up rather than moving off the critical path.
The idle barely shifts.

**Backend sampling (`-bs`) removes the largest host cost and the wall clock does not move.** The
server normally copies the whole logits row to the host every pass so the CPU can sample it; the
flag samples on the GPU instead. The transfer really does disappear and the idle really does shrink
— and `radix_sort`, `argsort` and `cumsum` simply appear on the GPU instead, which now spends the
time the CPU gave up. Worse, it adds a flat **450 ms to every prefill**, which a profile of long
generations cannot see and a turn that runs eight to ten prefills pays eight to ten times. Reverted.

Which leaves the larger share, the kernels. No flag in this article reaches it, and it is not
peculiar to this box: [llama.cpp #27050](https://github.com/ggml-org/llama.cpp/issues/27050)
profiles the same decode loop on an RTX 5090 with a different model and lands in the same place.

*One caveat. The figures above are the benchmark's. A server is idler still — it also samples,
serves HTTP, tracks slots and checks drafts — so the agent gives up a little more than this, and
none of it to the memory bus.*

---

## Conclusion

The question at the top was how much you can get out of a DGX Spark before deciding it is not
enough to run an agent on. The answer is that it is enough: **45 t/s to over 100 on the turns that
matter**, six changes, each one measured.

**And the agent does not run the model that won.** As of these tests it runs Qwen3.6-35B-A3B — the
model Stage 6 shows losing at every context depth.

Gemma wins tokens per second and loses turns. It reasons about twice as much per round, hedges and
re-checks answers it already has, and on long log processing it was the model that looped. A round
it has to take back costs more than a round it finishes quickly, so the slower model finishes the
work sooner and the turns feel shorter.

**Nothing above could have predicted that.** Every stage measures a rate; none of them measures how
many rounds a question takes. Single-prompt tokens per second is a real number — taken honestly
here, and taken honestly by most people who publish one — and on its own it does not decide whether
an agent is good to use.

---

## Lessons learned

**Optimise the context before the machine.** Cutting the context a turn actually needs, from ~150k
tokens to ~10k, was worth more than every stage below combined — though not on the number this
article is about. On decode it is about 1.8×, against about 1.6× for all six stages at 64k. On the
wait before the first token appears it is better than twenty times, and that is the one a person
feels. Where those tokens were hiding, and the curves that set the target, are
[their own article]({{ site.baseurl }}/posts/context-before-the-runtime/).

What belongs here is the order. Tuning the runtime first would have meant optimising the machine to
process tokens that did not need to exist, and no amount of tuning reduces a token count.

**Read the file, not the filename.** `UD-Q4_K_XL` contains no Q4_K tensors. "26B-A4B" implies 4B
active parameters, but a forward pass also reads attention, embeddings and the dense FFN every
time — 63% of per-token bytes. Both facts come free from the GGUF header, and both change what you
would optimise.

**On a sparse MoE at batch 1, the sparse part is the minority.** This inverts the intuition that
expert weights are where the money is, and it decides which quantization formats can help you at
all: anything that compresses only the experts is optimising the part that is mostly asleep.

**A headline feature can be worth nothing to you.** NVFP4 is a large part of why a GB10 looks
attractive on paper, and it was one of the reasons I chose this box. For this workload it reached
none of the path a token actually reads — a capability on a spec sheet is only yours if it lands
where your workload spends its bytes.

**KV quantization buys context length, not speed — and on some architectures it costs dearly.**
Gemma gives up 49.5% at 64k for a quantized cache and GLM 75%, while Qwen gives up nothing. What
predicts it is attention design rather than vendor: models engineered for a *small* KV cache pay
for quantizing it, because per-element dequantization no longer hides beneath the bandwidth it
saves. The reflex to reach for `-ctk q8_0` is right about the memory and can be badly wrong about
the time.

**Do not expect the number on the box, and do not read the shortfall as a fault.** Here the bus
gives a running model about 90% of its spec sheet and the engine converts that into 70% — roughly
seventy cents on the advertised dollar, which is a fair expectation rather than a disappointment.
The two shares have different owners: what the kernel and the allocator do with memory is outside
your reach, and what the inference engine does with the bandwidth it gets is not. Knowing which is
which is the difference between tuning and wishing.

**New hardware means an immature toolchain, and the number worth finding is the one that unblocks
you.** None of this worked out of the box. GB10 support in llama.cpp arrived piecemeal, and getting
a build that actually used the hardware took several attempts — the evidence is still sitting in
[the build flags](#the-build): `CMAKE_CUDA_ARCHITECTURES=121a-real` and an ARMv9.2 CPU target are
not defaults, and getting them wrong leaves you a binary that runs, runs slow, and says nothing in
the logs about why. MTP landed later and `llama-bench` still cannot drive
it. NVFP4 has not usefully landed at all.

The temptation with a toolchain that green is to wait for it. The better move was to find the rate
at which the agent became developable — 45 t/s, here — and start building on it. The ecosystem
improves on its own schedule as the user base grows, and every gain in this article arrived on an
agent that had been in daily use for weeks. Optimising a system nobody is using yet is the same
mistake as optimising context you have not cut.
