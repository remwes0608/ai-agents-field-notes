# scripts

Diagnostics for the llama.cpp backend on `gb10`. Neither is part of the bot; both exist
because reasoning about decode speed from a spec sheet went wrong, repeatedly.

## The two-number method

Decode on a bandwidth-bound model is governed by one ratio, and each script measures one
side of it:

```
efficiency  =  (bytes read per token  x  tokens/s)  /  achievable bandwidth
                         active.py         measured      bw.py
```

Get both and you know whether a slow model is the hardware's fault or the engine's. Get
neither and you will divide a spec-sheet figure by a marketing parameter count, which is
what we did all evening and it was wrong in both terms.

| | measures | needs |
| --- | --- | --- |
| `bw.py` | achievable GPU memory bandwidth, no model involved | torch + CUDA |
| `active.py` | bytes one token actually reads, from a GGUF header | nothing |

## Usage

```sh
# what the bus will actually give you
ssh <host> 'cd ~/Projects/test-project && .venv/bin/python bw.py --achieved 157'

# what a token costs, and the efficiency that implies
python3 active.py ~/.cache/huggingface/hub/…/model.gguf --tps 71.8
```

`bw.py` needs a torch with CUDA; on gb10 the venv left over from an abandoned vLLM
attempt has one, which is the only thing that venv has ever been good for.

## What they found (2026-09-09, gemma-4-26B-A4B on GB10)

```
spec sheet                273 GB/s
achievable (bw.py)        247 GB/s     91% of spec — the hardware is fine
llama.cpp decode          157 GB/s     64% of achievable
```

And the byte count that goes with it, which is the half people usually guess:

```
always-active   1.29 GiB   attention + embeddings + dense FFN, every token
8/128 experts   0.75 GiB
per pass        2.04 GiB   — lower than the 2.25 GB "A4B" implies
```

Two conclusions worth carrying:

**The always-active path is 63% of per-token bytes.** On a sparse MoE at batch 1 the
routed experts are the *minority* component. Optimizing the experts — which is what every
NVFP4 conversion of this model does — improves the part that is mostly asleep and leaves
the hot path alone. That is why those builds measured half the speed of plain Q4_0.

**There is 1.57x sitting in the inference engine.** Not the silicon, which sustains 91% of
its spec. Where the missing third of the bus goes is still unknown; the MoE gather is the
first place we would look.

Full write-up: [`blog/2026-09-09-dgx-spark-tokens-per-second.md`](../blog/2026-09-09-dgx-spark-tokens-per-second.md).
