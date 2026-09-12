---
layout: page
title: About
description: What the agent is, how the project started, and the machine it runs on.
background: '/img/bg-about.svg'
---

Field notes from running an AI agent on **private hardware and open-weights models**, to
autonomously operate internal infrastructure.

What gets written up here is what was **measured**, including the occasions the measurement
overturned the conclusion. Every figure carries the metric it came from and the workload it was
taken under, because a throughput number without those is not a measurement.

## The agent

The agent answers questions about infrastructure and software, and runs automation: it reacts to
events and executes rules. All of it runs on one DGX Spark on open weights, and nothing leaves the
network.

<img src="{{ site.baseurl }}/drawings/agent-architecture.svg" alt="Architecture of the agent: Discord chat, Discord voice and an event bus feed an agent; a context builder assembles memory, rules and signals; the agent talks to a speech-to-text model, the Qwen LLM and a text-to-speech model, and reaches Kubernetes, Grafana, Harbor and GitHub through an MCP router." style="width:100%;max-width:660px;display:block;margin:1.5rem auto;">

*Green is the agent architecture. Everything else is a model, a transport, or a system it
reaches.*

**Two interfaces and a bus.** Discord chat is the primary interface. Discord voice runs through
Parakeet for speech-to-text on the way in and Chatterbox for text-to-speech on the way back, which
exercises a path text never touches.

**Everything asynchronous goes through the event bus**, which is why it belongs to the architecture
rather than sitting outside it as a transport. It does three jobs at once. Events arrive on it —
eBPF, Kubernetes, Harbor, CI/CD. Agents talk to each other across it: one instance's output is
another instance's event, so they chain through the bus rather than calling each other directly.
And a turn can use it outbound, calling a tool that starts an asynchronous job and returning before
that job is done.

That decides what those turns cost. Nobody watches an event-driven turn arrive, which is not the
same as nobody waiting for it — somebody is waiting on a deployment and the automated smoke tests
behind it, and that answer comes at the end of the chain rather than at a first token. Context
discipline matters more here rather than less: these turns share one finite runtime, and an
automated turn carrying a fat prompt spends capacity the next link in the chain is queued behind.

**The context builder decides what a turn costs.** Nothing reaches the model that it has not
assembled: retrieved memory, the rule files that say what to do about an event, and the signal
files that say what is worth noticing in the first place. That surface is what
[the context article]({{ site.baseurl }}/posts/context-before-the-runtime/) is about — the price of
a turn is set here, before the model sees a token.

**One model does the reasoning.** Qwen3.6-35B-A3B, with Gemma 4 resident as a fallback, and a LoRA
adapter for the behaviour that is cheaper to train in than to instruct — formatting compliance
rather than anything to do with knowledge.

**Everything outward goes through one MCP router.** Kubernetes, Grafana, Harbor and GitHub are what
the agent sees; behind them sit the clusters themselves, Loki and Alloy for logs, Prometheus for
metrics, Falco for runtime security events, a 5G core, and a long tail of others already wired in —
the diagram names a few of them. GitHub closes the
loop back into the signal files. The router is also where the tool catalogue lives, and the
catalogue is the single largest thing deciding what a turn costs.

**A second agent is coming, and it will chain with this one through the bus.** Compliance control
and SDLC process optimisation, built on the same architecture — not as a bigger agent but as
another instance whose events this one can raise and consume. That is the payoff of putting the bus
in the middle: a second agent is a deployment rather than a redesign, and everything measured here
about the runtime applies to it unchanged.

## What a real session looks like

The measurements that matter come from real turns, and real turns here are overwhelmingly manual
tests: *is this service healthy*, *how many clients are configured*, *check authentication
attempts over the last 24 hours*. They are multi-round — the agent calls a tool, reads the result,
calls another — and a person is watching a "thinking" indicator the whole time.

That shape decides everything downstream: the turn is read-heavy rather than generation-heavy, and
latency-sensitive in a way a batch job is not. Everything below follows from it.

## How this project got here

The agent idea started about a year ago, around **autonomous 5G Core**. The first promising open
source initiatives were appearing, and my team and I were finishing a round of cloud-native
optimisation work. The natural next step was full autonomy — self-operating software, deployable
into any Kubernetes cluster.

**Kubernetes cluster management automation was the first quick win.** Once we started looking, we
found useful events arriving from everywhere: CI/CD pipelines, Kubernetes events, eBPF. Each was
individually informative and collectively unused. Connecting them into one agent was the obvious
opportunity.

At that point an evaluation of **LangChain / LangGraph** was pending and not really progressing —
there was a lot of activity there and many discussions, but the results were questionable, and a
year later I still cannot say whether it is the right direction. So the decision was: build
something from scratch, gain the experience and the knowledge, then decide — and meanwhile watch
where the whole story goes. Looking at the market since, a lot of organisations appear to have
taken the same path.

**Discord was partly a joke and mostly a shortcut.** It was funny, and it was also genuinely
attractive: everybody already communicates through it or something like it, so why spend time
building another chat UI? Use the thing people already know and have adopted, and spend the
available time on agent problems instead — of which there are many.

That had consequences in both directions. It is somebody else's platform with somebody else's
constraints, and the agent has to live inside them. On balance it has been more win than cost, and
it went from a convenience to my primary interface to infrastructure faster than expected.

**It also turned out to provide test pressure**, which a purpose-built UI would not have: multi-user
chats are genuine concurrency rather than a synthetic load, voice exercises a path text never
touches, and being always there means the agent gets used casually enough to find the awkward
cases. None of that is a capability; all of it is useful for finding out where the agent breaks.

## The machine, and why this one

An **NVIDIA DGX Spark (GB10)**: a Grace-Blackwell superchip with 20 ARM cores, a Blackwell GPU, and
**128 GB of unified memory** at up to **273 GB/s**. Unified memory is the defining property. There
is no separate VRAM budget, so a 26–35B model and its cache and the operating system all draw on
the same pool, and nothing in that class is too large to load. Capacity is not the constraint here.
**Bandwidth is**, and every measurement on this site is downstream of that.

The choice was between an **RTX 6000** and a **GB10**. The RTX 6000 is still the reference for a
production inference box and nothing here argues otherwise — but this is not a production box. It
is one machine that has to be available all day, next to a desk, for an agent that is idle most of
the time and wanted instantly. A workstation card is built to be fed power and cooled hard while it
works; GB10 is built to sit there — near-silent, and drawing less under load than a workstation card
does at rest. For a single always-on agent, that and the memory it comes with mattered more than
peak throughput.

## Making it fast enough

It started at roughly **45 t/s**, and whether that would ever be enough was the open question —
both major runtimes were rough on this hardware, and getting a sparse MoE serving an agent at all
was the achievement. Two phases of work answered it, in this order.

**First the context, deliberately.** A turn's cost is roughly *tokens processed* × *cost per token*,
so halving the context halves the work regardless of how fast the hardware runs; tuning the runtime
first would have meant optimising the machine to process tokens that did not need to exist. Context
per turn came down from roughly **150k tokens to roughly 10k** with no loss in answer quality — a
dozen small cuts rather than one clever one, the largest of them about 35k tokens of tool schemas
that almost nothing ever called.
[The context article]({{ site.baseurl }}/posts/context-before-the-runtime/) has that work and the
two curves that set the target.

**Then the runtime**, once the remaining cost was genuinely the runtime's: six changes, one at a
time, each measured before the next, ending **over 100 t/s** on the turns that matter.
[The tuning article]({{ site.baseurl }}/posts/dgx-spark-performance/) has the stages, the
measurements, and the one number neither phase could account for.

## Why Gemma, and why Qwen now

Because **Gemma 3 was the first model that did not lie to me.** Asked something it could not
determine, it said "I don't know" rather than inventing a plausible answer.

I had real problems with DeepSeek and Qwen hallucinations at the time. The community rated both
highly; my experience did not match, and the answer may well have been tuning or configuration I
did not have time to pursue. What that left me with was the habit of evaluating a model against my
own purpose rather than against a leaderboard — which is what eventually changed the answer.

**As of these tests the agent runs Qwen3.6-35B-A3B.** Gemma 4 is still resident as the fallback.
Qwen is *not* the faster model on paper — Gemma wins the throughput benchmark at every context
depth — but Qwen makes fewer mistakes while reasoning, and a round it does not have to take back is
worth more than a round it finishes quickly. The turns feel faster because there are fewer of them.


## Code and scripts

The diagnostic scripts these articles were measured with are published in the
[repository](https://github.com/remwes0608/ai-agents-field-notes/tree/main/scripts).

## Licence

Prose and measurements are CC BY 4.0; code and configuration snippets are MIT.
