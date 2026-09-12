#!/usr/bin/env python3
"""Read a GGUF header and report how many bytes one token actually costs.

Why this exists: on a sparse MoE the marketing name understates what decoding reads.
"26B-A4B" suggests ~4B active parameters, but a forward pass also drags in attention,
embeddings and the dense FFN every single time — and on gb10 those turned out to be
*63% of per-token bytes*, with the eight routed experts a minority component. Getting this
wrong sends you optimizing the part of the model that is mostly asleep. It is exactly why
the NVFP4 builds lost: they compressed the experts and left the always-active path at BF16.

Needs no GPU and no inference engine — it parses the file header directly, so it works on
any GGUF you have on disk, including ones you are deciding whether to download.

Pair with bw.py, which measures the bandwidth these bytes have to cross:

    decode efficiency  =  (bytes per token x tokens/s) / measured bandwidth

Run:

    active.py /path/to/model.gguf

Measured on unsloth/gemma-4-26B-A4B-it-qat-GGUF:UD-Q4_K_XL (2026-09-09):

    attention (always)     0.58 GiB
    embeddings/output      0.39 GiB
    dense ffn (always)     0.32 GiB
    ------------------------------
    always-active          1.29 GiB
    8/128 of experts       0.75 GiB
    per forward pass       2.04 GiB      <- lower than the 2.25 GiB we had assumed

At 87.9 t/s that is 193 GB/s, against the 237 GB/s the bus delivers read-only: 81%
efficiency. Note the unit change: sizes are GiB (2^30), throughput is decimal GB/s (1e9),
which is what the spec sheet quotes. Conflating them moves the ratio by 7%.
"""
import argparse, collections, struct, sys

# ggml type -> (bytes per block, elements per block)
GGML = {0: (4, 1), 1: (2, 1), 2: (18, 32), 3: (20, 32), 6: (22, 32), 7: (24, 32),
        8: (34, 32), 9: (36, 32), 10: (84, 256), 11: (110, 256), 12: (144, 256),
        13: (176, 256), 14: (210, 256), 30: (2, 1), 39: (17, 32), 40: (18, 32)}
GiB = 2 ** 30


def read_header(path):
    f = open(path, "rb")
    if f.read(4) != b"GGUF":
        raise SystemExit(f"{path}: not a GGUF file")
    struct.unpack("<I", f.read(4))                       # version
    n_tensors, = struct.unpack("<Q", f.read(8))
    n_kv, = struct.unpack("<Q", f.read(8))

    def rstr():
        n, = struct.unpack("<Q", f.read(8))
        return f.read(n).decode("utf-8", "replace")

    def rval(t):
        simple = {0: "<b", 1: "<B", 2: "<h", 3: "<H", 4: "<i", 5: "<I",
                  6: "<f", 7: "<?", 10: "<q", 11: "<Q", 12: "<d"}
        if t == 8:
            return rstr()
        if t == 9:
            et, = struct.unpack("<I", f.read(4))
            ln, = struct.unpack("<Q", f.read(8))
            return [rval(et) for _ in range(ln)]
        fmt = simple[t]
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]

    kv = {}
    for _ in range(n_kv):
        k = rstr(); t, = struct.unpack("<I", f.read(4)); kv[k] = rval(t)

    roles, types = collections.Counter(), collections.Counter()
    for _ in range(n_tensors):
        name = rstr()
        nd, = struct.unpack("<I", f.read(4))
        dims = struct.unpack("<" + "Q" * nd, f.read(8 * nd))
        tt, = struct.unpack("<I", f.read(4))
        f.read(8)                                        # offset
        n = 1
        for d in dims:
            n *= d
        bs, bn = GGML.get(tt, (4, 1))
        nbytes = n // bn * bs
        # "_exps" is llama.cpp's naming for routed expert tensors; everything else is read
        # on every token.
        if "_exps" in name:
            role = "experts (sparse)"
        elif "attn" in name:
            role = "attention (always)"
        elif "ffn" in name:
            role = "dense ffn (always)"
        elif "embd" in name or name.startswith("output"):
            role = "embeddings/output"
        else:
            role = "norms/other (always)"
        roles[role] += nbytes
        types[tt] += nbytes
    return kv, roles, types, n_tensors


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("gguf", help="path to a .gguf file")
    ap.add_argument("--tps", type=float, help="measured tokens/s, to imply achieved bandwidth")
    ap.add_argument("--bandwidth", type=float, default=247.0,
                    help="measured achievable GB/s from bw.py (default: gb10's 247)")
    a = ap.parse_args()

    kv, roles, _, n_tensors = read_header(a.gguf)
    arch = kv.get("general.architecture", "?")
    n_exp = kv.get(f"{arch}.expert_count")
    n_use = kv.get(f"{arch}.expert_used_count")

    total = sum(roles.values())
    print(f"{a.gguf}")
    print(f"  arch={arch}  tensors={n_tensors}  experts={n_exp} used={n_use}")
    print(f"\n  file total {total/GiB:.2f} GiB")
    for k, v in roles.most_common():
        print(f"    {k:<22} {v/GiB:>7.2f} GiB")

    if not (n_exp and n_use):
        print("\n  Dense model — every byte above is read per token.")
        per = total
    else:
        exps = roles["experts (sparse)"]
        always = total - exps
        share = exps * n_use / n_exp
        per = always + share
        print(f"\n  per token, with {n_use}/{n_exp} experts routed:")
        print(f"    always-active        {always/GiB:>7.2f} GiB   ({100*always/per:.0f}% of the read)")
        print(f"    routed experts       {share/GiB:>7.2f} GiB")
        print(f"    ---------------------------------")
        print(f"    PER FORWARD PASS     {per/GiB:>7.2f} GiB")

    if a.tps:
        achieved = per * a.tps / 1e9
        print(f"\n  at {a.tps:g} t/s that is {achieved:.0f} GB/s")
        print(f"  against {a.bandwidth:g} GB/s achievable -> {100*achieved/a.bandwidth:.0f}% efficiency")
        if achieved < a.bandwidth * 0.9:
            print(f"  {a.bandwidth/achieved:.2f}x headroom, in the engine rather than the silicon")


if __name__ == "__main__":
    main()
