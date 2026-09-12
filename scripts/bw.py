#!/usr/bin/env python3
"""Measure achievable GPU memory bandwidth, with no inference engine in the way.

Why this exists: decode throughput on a bandwidth-bound model is often reasoned about by
taking a spec-sheet number and dividing. On gb10 that was wrong twice over — the spec
sheet says 273 GB/s, the bus delivers 237 read-only, and llama.cpp's decode path achieves
the equivalent of 193. Only the last of those is a limit you can do anything about, and
you cannot see it without measuring the middle one.

Read-only is the figure to compare against, not copy: decode reads weights, it does not
copy them.

Units: throughput here is decimal GB/s (1e9 bytes), because that is what spec sheets
quote. Buffer sizes are GiB (2^30). Mixing the two silently inflates an efficiency ratio
by 7%.

Pair this with active.py, which gives the other half: bytes actually read per token.

    decode efficiency  =  (bytes per token x tokens/s) / measured bandwidth

Run (needs torch with CUDA; on gb10 the venv from an old vLLM attempt has one):

    ssh <host> 'cd ~/Projects/test-project && .venv/bin/python /path/to/bw.py'

Measured on gb10 (DGX Spark GB10, torch 2.11+cu130, 2026-09-09):

    copy   (read+write)   247.4 GB/s     <- 91% of the 273 GB/s spec sheet
    read   (reduction)    237.8 GB/s
    triad  (2r + 1w)      235.0 GB/s

Take the read-only figure as "what the bus will give you" for decode. Optionally pass the
rate your inference engine achieves to get the efficiency ratio directly:

    bw.py --achieved 193
"""
import argparse, torch

GiB = 1024 ** 3   # buffer sizing only; throughput below is decimal GB/s


def bench(label, fn, bytes_moved, iters=12, warmup=3):
    for _ in range(warmup):
        fn()
    torch.cuda.synchronize()
    ts = []
    for _ in range(iters):
        s = torch.cuda.Event(True); e = torch.cuda.Event(True)
        s.record(); fn(); e.record(); torch.cuda.synchronize()
        ts.append(s.elapsed_time(e) / 1000.0)
    ts.sort()
    best, med = ts[0], ts[len(ts) // 2]
    print(f"  {label:<34} best {bytes_moved/best/1e9:>7.1f} GB/s   "
          f"median {bytes_moved/med/1e9:>7.1f} GB/s")
    return bytes_moved / best / 1e9


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--gib", type=float, default=4.0, help="buffer size per tensor (default 4)")
    ap.add_argument("--spec", type=float, default=273.0, help="spec-sheet GB/s for comparison")
    ap.add_argument("--achieved", type=float,
                    help="GB/s your inference engine achieves, to print an efficiency ratio")
    a = ap.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("no CUDA device visible")
    dev = torch.device("cuda")
    print(f"device: {torch.cuda.get_device_name(0)}   torch {torch.__version__}")

    n = int(a.gib * GiB)
    x = torch.empty(n, dtype=torch.uint8, device=dev); x.fill_(1)
    y = torch.empty(n, dtype=torch.uint8, device=dev); y.fill_(2)
    torch.cuda.synchronize()
    print(f"\nbuffers: 2 x {a.gib:g} GiB uint8\n")

    results = [bench("copy  dst.copy_(src)   [read+write]", lambda: y.copy_(x), 2 * n)]
    xf, yf = x.view(torch.float32), y.view(torch.float32)
    results.append(bench("read  a.sum()          [read only]", lambda: xf.sum(), n))
    out = torch.empty_like(xf)
    results.append(bench("triad c = a + b        [2r + 1w]",
                         lambda: torch.add(xf, yf, out=out), 3 * n))

    best = max(results)
    print(f"\n  spec sheet          {a.spec:>7.1f} GB/s")
    print(f"  best measured       {best:>7.1f} GB/s   ({100*best/a.spec:.0f}% of spec)")
    if a.achieved:
        print(f"  your engine         {a.achieved:>7.1f} GB/s   "
              f"({100*a.achieved/best:.0f}% of measured)")
        if a.achieved < best * 0.9:
            print(f"\n  {best/a.achieved:.2f}x headroom sits in the inference engine, not the silicon.")
        else:
            print("\n  The engine is at or near achievable bandwidth.")


if __name__ == "__main__":
    main()
