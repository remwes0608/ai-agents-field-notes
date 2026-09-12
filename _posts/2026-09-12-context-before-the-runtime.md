---
title: "Cutting an agent's turn from 150k to 10k tokens"
subtitle: "Where the tokens were hiding, and why it came before the tuning"
background: "/img/bg-post.svg"
---

**The obvious way to make a slow agent faster is to make the hardware faster. The cheaper way is to
stop handing it work that did not need to exist.**

A turn's cost is roughly *tokens processed* × *cost per token*. Halving the context halves the work
whatever the hardware does, and it is the only one of the two factors you fully control. So before
touching the runtime I went after the tokens: context per turn came down from roughly **150k to
roughly 10k**, with no loss in answer quality.

No single change did that. It was a set of small cuts, and this article shows one of them in full
— **about 35k tokens of tool schemas that almost nothing ever called** — because it is the one with
a clean measurement and a simple fix. The shape of it repeats everywhere else.

This is the half that came first. The runtime tuning that followed is
[a separate article]({{ site.baseurl }}/posts/dgx-spark-performance/), and cutting the context was worth more
than all six of its stages on the number a person actually feels.

The machine throughout is an NVIDIA DGX Spark (GB10) running a 35B sparse MoE through llama.cpp.
The workload is an infrastructure agent: multi-round tool-calling turns, a person watching, **9–17
prompt tokens read for every token generated**. Expect different absolute numbers on other
hardware. The shape is what transfers.

---

## A turn has two waits, and only one of them is visible

Both halves of a turn's cost move with context length, and they move differently.

Generation slows gradually:

<svg viewBox="0 0 700 270" width="100%" role="img" aria-label="Decode throughput against context size: 69 tokens per second at zero context falling to 36 at 150,000.">
  <line x1="60" y1="30" x2="60" y2="230" stroke="#bbb"/>
  <line x1="60" y1="230" x2="670" y2="230" stroke="#bbb"/>
  <line x1="60" y1="230.0" x2="670" y2="230.0" stroke="#eee"/>
  <text x="54" y="234.0" text-anchor="end" font-size="11" fill="#777">0</text>
  <line x1="60" y1="180.0" x2="670" y2="180.0" stroke="#eee"/>
  <text x="54" y="184.0" text-anchor="end" font-size="11" fill="#777">20</text>
  <line x1="60" y1="130.0" x2="670" y2="130.0" stroke="#eee"/>
  <text x="54" y="134.0" text-anchor="end" font-size="11" fill="#777">40</text>
  <line x1="60" y1="80.0" x2="670" y2="80.0" stroke="#eee"/>
  <text x="54" y="84.0" text-anchor="end" font-size="11" fill="#777">60</text>
  <line x1="60" y1="30.0" x2="670" y2="30.0" stroke="#eee"/>
  <text x="54" y="34.0" text-anchor="end" font-size="11" fill="#777">80</text>
  <text x="60.0" y="248" text-anchor="middle" font-size="11" fill="#777">0</text>
  <text x="125.5" y="248" text-anchor="middle" font-size="11" fill="#777">16k</text>
  <text x="322.1" y="248" text-anchor="middle" font-size="11" fill="#777">64k</text>
  <text x="660.0" y="248" text-anchor="middle" font-size="11" fill="#777">150k</text>
  <text x="365" y="262" text-anchor="middle" font-size="11" fill="#777">context (tokens)</text>
  <text x="16" y="130" text-anchor="middle" font-size="11" fill="#777" transform="rotate(-90 16 130)">decode t/s</text>
  <polyline points="60.0,56.6 76.4,60.6 125.5,72.7 322.1,106.2 660.0,140.7" fill="none" stroke="#2c6fad" stroke-width="2.5"/>
  <circle cx="60.0" cy="56.6" r="3.5" fill="#2c6fad"/>
  <text x="67.0" y="49.6" font-size="11" fill="#333">69</text>
  <circle cx="76.4" cy="60.6" r="3.5" fill="#2c6fad"/>
  <text x="83.4" y="53.6" font-size="11" fill="#333">68</text>
  <circle cx="125.5" cy="72.7" r="3.5" fill="#2c6fad"/>
  <text x="132.5" y="65.7" font-size="11" fill="#333">63</text>
  <circle cx="322.1" cy="106.2" r="3.5" fill="#2c6fad"/>
  <text x="329.1" y="99.2" font-size="11" fill="#333">50</text>
  <circle cx="660.0" cy="140.7" r="3.5" fill="#2c6fad"/>
  <text x="667.0" y="133.7" font-size="11" fill="#333">36</text>
</svg>

*Decode rate against context depth. `llama-bench`, Qwen3.6-35B-A3B at `f16` KV, `tg128`, `-r 2`,
±0.50 or better.*

Time before the first token does not slow gradually. It runs away, because the whole prompt has to
be read before anything can be written, and the rate at which it is read drops as it gets longer:

<svg viewBox="0 0 700 270" width="100%" role="img" aria-label="Time before the first token against context size: under two seconds at 4,000 tokens, 90 seconds at 150,000. A five-second patience line is crossed at about 11,000 tokens.">
  <rect x="60" y="30" width="610" height="189.5" fill="#d94f4f" opacity="0.05"/>
  <line x1="60" y1="30" x2="60" y2="230" stroke="#bbb"/>
  <line x1="60" y1="230" x2="670" y2="230" stroke="#bbb"/>
  <line x1="60" y1="230.0" x2="670" y2="230.0" stroke="#eee"/>
  <text x="54" y="234.0" text-anchor="end" font-size="11" fill="#777">0</text>
  <line x1="60" y1="166.8" x2="670" y2="166.8" stroke="#eee"/>
  <text x="54" y="170.8" text-anchor="end" font-size="11" fill="#777">30 s</text>
  <line x1="60" y1="103.7" x2="670" y2="103.7" stroke="#eee"/>
  <text x="54" y="107.7" text-anchor="end" font-size="11" fill="#777">60 s</text>
  <line x1="60" y1="40.5" x2="670" y2="40.5" stroke="#eee"/>
  <text x="54" y="44.5" text-anchor="end" font-size="11" fill="#777">90 s</text>
  <text x="60.0" y="248" text-anchor="middle" font-size="11" fill="#777">0</text>
  <text x="125.5" y="248" text-anchor="middle" font-size="11" fill="#777">16k</text>
  <text x="322.1" y="248" text-anchor="middle" font-size="11" fill="#777">64k</text>
  <text x="660.0" y="248" text-anchor="middle" font-size="11" fill="#777">150k</text>
  <text x="365" y="262" text-anchor="middle" font-size="11" fill="#777">context (tokens)</text>
  <text x="16" y="130" text-anchor="middle" font-size="11" fill="#777" transform="rotate(-90 16 130)">before first token</text>
  <line x1="106.0" y1="30" x2="106.0" y2="230" stroke="#d94f4f" stroke-width="1.5" stroke-dasharray="5 4"/>
  <text x="114.0" y="44" font-size="11.5" fill="#d94f4f" font-weight="600">~11k tokens</text>
  <text x="114.0" y="58" font-size="11" fill="#d94f4f">patience runs out here</text>
  <line x1="60" y1="219.5" x2="670" y2="219.5" stroke="#d94f4f" stroke-width="1.5" stroke-dasharray="5 4"/>
  <text x="64" y="213.5" font-size="11" fill="#d94f4f">5 s</text>
  <polyline points="60.0,230.0 76.4,226.4 125.5,214.9 322.1,161.5 660.0,40.7" fill="none" stroke="#2c6fad" stroke-width="2.5"/>
  <circle cx="76.4" cy="226.4" r="3.5" fill="#2c6fad"/>
  <circle cx="125.5" cy="214.9" r="3.5" fill="#2c6fad"/><text x="133.5" y="206.9" font-size="11" fill="#333">7</text>
  <circle cx="322.1" cy="161.5" r="3.5" fill="#2c6fad"/><text x="330.1" y="153.5" font-size="11" fill="#333">33</text>
  <circle cx="660.0" cy="40.7" r="3.5" fill="#2c6fad"/><text x="668.0" y="32.7" font-size="11" fill="#333">90</text>
  <circle cx="106.0" cy="219.5" r="4" fill="#d94f4f"/>
</svg>

*The same model and settings, prompt-processing rate turned into wall-clock. Measured `pp` rates:
2,389 t/s at 4k, 2,288 at 16k, 1,997 at 64k, 1,647 at 150k, ±20 or better.*

Over the same range decode loses about **half** its rate. Time to first token goes from under two
seconds to **more than a minute and a half** — better than fifty times worse. One of these is a
curve; the other is a cliff.

---

## Five seconds is not folklore here, it is the reporting interval

The agent buys patience by showing its work: its Discord presence updates as it picks a tool, calls
it, reads the result back. A person will wait a long time while something is visibly happening, and
gives up quickly when nothing is. **Cancellations come from silence rather than from slowness.**

That is what makes the second curve worse than it looks. Decode is reportable — tokens are
arriving, rounds are completing, the presence has something to say and keeps saying it. Prefill is
dead air. No token exists yet, no tool has been called, nothing has happened that can be described,
and the only honest thing to display is a spinner.

Five seconds of patience buys about **eleven thousand tokens** of context on this machine. A turn
that fits in ten thousand answers before anyone gives up on it. A turn carrying a hundred and fifty
thousand has lost the room before it begins — ninety seconds of spinner is not a slow answer, it is
an answer nobody stayed for.

That is the whole of the target. Not a token budget chosen for tidiness: the largest prompt that
still starts talking inside one reporting interval.

**The automated half of the workload has no reporting interval and arrives at the same discipline
anyway.** Nobody watches an event-driven turn. Somebody is still waiting on the deployment and the
automated smoke-test results behind it, and that answer lands at the end of a chain of orchestrated
steps rather than at a first token — each step's prefill compounding into one total that is
invisible until it is over.

And those turns share the runtime with the watched ones. A slot occupied by a
hundred-and-fifty-thousand-token prompt is a slot the next event queues behind, so an automated
turn's context is charged twice: once to itself, and once to everything waiting on it. Human
patience and machine throughput turn out to be two arguments for the same budget.

---

## The clearest example: the tool catalogue

**The reduction came from a dozen places, none of them dramatic.** The agent's identity and
formatting instructions. What it is allowed to remember, and for how long. The event rules and the
signal selectors that decide what an automated turn is even shown. The conversation history policy.
Each was worth a few thousand tokens; each took a while to get right; none of them is interesting
on its own, and listing them all would be a different and worse article.

The tool catalogue is the one worth showing in full. It is the largest single item, it has a clean
measurement, and the fix turned out to be simple — which makes it the best illustration of the
thing they all have in common: **a cost that is invisible until someone goes looking for it.**

What it was not, in any of these cases, was the conversation.

A single real turn, question *"what are you?"*, measured against the deployed model's own
tokenizer:

| | tokens |
| --- | --- |
| whole prompt | 36,670 |
| the conversation in it | ~1,900 |
| **tool declarations** | **~34,800** |

**95% of that prompt was schemas.** The question was four words. That ratio is one prompt on one
day, not a constant — but every turn that day paid some version of it.

Four MCP servers had been connected over time, each one individually reasonable:

| server | tools declared | tokens | tokens per tool | tools ever called |
| --- | --- | --- | --- | --- |
| container registry | 44 | 18,119 | 411 | 4 |
| Kubernetes | 23 | 5,699 | 247 | 16 |
| metrics | 68 | — | — | 9 |
| chat (in-process) | 18 | — | — | 8 |
| **total** | **153** | **~34,800** | | **37** |

*Two servers were not reachable for direct tokenization; their share is the residual.*

Against 137 recorded sessions carrying **603 tool calls across 37 distinct tools** — and **348 of
those 603 calls were three tools**. A hundred and sixteen declared tools were never called once,
and every one of them was charged on every round of every turn.

**This is the trap, and it is structural rather than careless.** Connecting an MCP server is one
line of configuration, and the cost lands somewhere nobody is looking — not in a log, not in a
latency graph, but spread evenly across every future prompt. The server that cost 18,119 tokens a
turn was doing its job correctly.

The fix follows from the numbers: declare a small hot set and put the rest behind a lookup the
model can call when it needs something outside it. Replaying the corpus against candidate hot sets
says where to stop:

| declared hot set | sessions needing a lookup | extra rounds per session |
| --- | --- | --- |
| 0 | 96.6% | 2.42 |
| 8 | 40.7% | 0.73 |
| 12 | 19.5% | 0.37 |
| **20** | **8.5%** | **0.11** |

Twenty tools covers nine sessions in ten outright, and costs the tenth about a tenth of a round.
That is what runs in production now.

---

## The cache will not save you

The obvious objection is that none of this should matter, because a prompt cache means the prefill
is paid once.

It pays within a turn and mostly not across turns. Later rounds of one turn resend a byte-identical
prefix and prefill only the newly appended tool result, which is why round one is the expensive one
and the rest are not. But **automation assembles a different prompt for every event**, so there is
rarely a prefix to reuse; a chat session stays warm only briefly, and the next question may have
nothing to do with the last.

Keeping sessions warm long enough to help means carrying one question's context into the next,
which trades prefill time for the risk of answering the wrong thing. Most turns open cold and pay
round one in full.

There is a second reason to care, and it is the one that bites quietly. Prefix matching ends at the
first differing byte, so anything that varies per turn and sits near the front of the prompt
invalidates everything behind it — and a tool catalogue is exactly the kind of thing that gets
rewritten in place.

---

## Lessons learned

**Cut the context before tuning the machine.** Tuning first means optimising the hardware to
process tokens that did not need to exist. The order is not a preference: context reduction is
multiplicative with everything the runtime does afterwards, and nothing the runtime does afterwards
reduces the token count.

**Expect a dozen cuts, not one.** The reduction came from half a dozen unrelated places, none of
them dramatic, and the largest was about a third of it. Looking for the single big win would have
found nothing.

**Measure what is in the prompt before assuming it is the conversation.** In the prompt measured
here it was 95% schemas and 5% conversation, and no instrument on the box reported that. A turn's
token count is visible; its composition is not, and only the composition tells you what to cut.

**An MCP server's cost is not paid where you connect it.** It is one configuration line, and it is
charged on every round of every turn from then on, whether or not anything calls it. Connecting is
cheap and reversible; the bill is neither.

**Declare the tools that get used and reach the rest through a lookup.** Most of a declared
catalogue is never called, and what is called concentrates hard. A small hot set with a lookup
behind it covers nearly every session and costs a fraction of a round on the rare miss.

**Time to first token is the number a person feels, and it is the one that runs away.** Over the
same context range decode loses half its rate while the wait before anything appears gets more than
fifty times worse. Tokens per second is the figure everyone quotes and the milder of the two.

**Pick the budget from the workload, not from the model.** Ten thousand tokens is what fits inside
one reporting interval on this hardware, and the automated half of the workload lands on the same
number for its own reason. Change the machine or the interface and the number moves. The model has
nothing to do with it.
