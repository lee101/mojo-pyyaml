# mojo-pyyaml

`mojo-pyyaml` is a standalone YAML parser and emitter with its bulk lexical
work implemented in [Mojo](https://www.modular.com/mojo). Its Python module is
`mojopyyaml`, and its primary API mirrors PyYAML:

```python
import mojopyyaml as yaml

config = yaml.safe_load("""
service:
  name: search
  ports: [8080, 8443]
  enabled: true
""")

text = yaml.safe_dump(config, sort_keys=False)
assert yaml.safe_load(text) == config
```

PyYAML is installed only as a parity-test and benchmark reference.
`mojopyyaml` does not import it or delegate parsing or emitting to it.

## Scope

This port targets the common safe configuration and data-interchange subset.
The tested public entry points are `load`, `load_all`, `safe_load`,
`safe_load_all`, `full_load`, `full_load_all`, `unsafe_load`,
`unsafe_load_all`, `dump`, `dump_all`, `safe_dump`, and `safe_dump_all`.
Within those entry points, tests cover:

- block and flow mappings and sequences, including indentless sequences
- plain, single-quoted, double-quoted, literal (`|`), and folded (`>`) scalars
- YAML 1.1 null, Boolean, integer, float, sexagesimal, date, and timestamp
  resolution
- anchors, aliases, mapping merge keys, directives, document markers, and
  multi-document streams
- standard scalar tags for strings, nulls, Booleans, integers, floats,
  timestamps, and binary data
- `BaseLoader` string-only resolution, bytes and file-like input, encoded
  output, flow style, key sorting, indentation, document markers, version
  directives, line endings, and Unicode policy

This is not a complete PyYAML or YAML 1.1 implementation.
Custom and Python-specific tags, complex explicit keys, `!!set`, `!!omap`,
`!!pairs`, recursive alias cycles, custom constructors/representers, UTF-16
input, and PyYAML's token/event/node APIs are not implemented. `unsafe_load`
is an API-compatible name but does not instantiate arbitrary Python objects.
The emitter preserves values and insertion order but does not reproduce
comments, source formatting, or shared-object aliases.

## Install

```bash
pixi install
pixi run build
pixi run python - <<'PY'
import mojopyyaml as yaml

value = yaml.safe_load("service: {name: search, enabled: true}")
print(yaml.safe_dump(value, sort_keys=False), end="")
PY
```

This prints a YAML mapping with the same values. All project commands run
inside the pinned environment. The build produces
`dist/libmojo-pyyaml.so`; importing the package also rebuilds it when a Mojo
source is newer.

## Performance

Measured by `pixi run bench` against PyYAML's public `safe_load` and
`safe_dump` functions on an Intel Xeon E5-2697 v4 at 2.30 GHz, Linux
6.8.0-136-generic. These are the best of three end-to-end runs, including
Python object construction. Both implementations operate on the same input,
and the benchmark checks behavioral equality before timing.

| case | mojo-pyyaml | PyYAML | speedup |
| --- | ---: | ---: | ---: |
| load flat mapping (25k pairs) | 226.3 ms | 1537.6 ms | 6.80x |
| load records (5k mappings) | 132.6 ms | 1099.1 ms | 8.29x |
| dump flat mapping (25k pairs) | 85.8 ms | 938.0 ms | 10.93x |
| dump quoted scalar (2.0 MB) | 16.7 ms | 1790.8 ms | 107.54x |
| load flow sequence (25k scalars) | 118.8 ms | 779.6 ms | 6.56x |
| load quoted scalar (2.0 MB) | 74.5 ms | 1781.9 ms | 23.92x |
| dump quoted sequence (25k scalars) | 20.4 ms | 490.7 ms | 24.11x |

The reference is PyYAML's default pure-Python `SafeLoader`/`SafeDumper`, which
are what its `safe_load`/`safe_dump` convenience functions call. Optional
LibYAML `CSafeLoader` and `CSafeDumper` classes are outside this comparison.

GPU acceleration is intentionally omitted. The native kernels classify and
copy bytes with well under two operations per byte moved, so device allocation,
transfer, and launch overhead cannot be amortized. Profiling also showed that
Python grammar parsing and object construction dominate large structured loads;
the remaining independent per-line metadata work is too small to justify CPU
thread-launch overhead.

## How it works

Python owns strings, lists, dictionaries, scalar construction, and all
allocations. One Mojo compilation unit scans the UTF-8 byte buffer for line
boundaries, indentation, and trimmed spans, and performs the byte-oriented
escaping pass for double-quoted output. The recursive YAML grammar operates
on that compact line metadata.

The shared library uses a C ABI through `ctypes`. Contiguous NumPy buffers stay
owned and alive on the Python stack for each native call. Their addresses,
element counts, and output capacities cross the boundary; Mojo reconstructs
`UnsafePointer[..., AnyOrigin[mut=True]]` values inside non-parametric
`@export` functions only after rejecting null addresses and invalid sizes.
Metadata uses `int64` on both sides and byte buffers use `uint8`, avoiding
implicit dtype narrowing. Output buffers are allocated by Python and filled
by Mojo, so ownership never crosses the FFI and there is no cross-runtime
allocator pairing.

## Development

```bash
pixi run build
pixi run test
pixi run bench
```

The benchmark task holds `/tmp/mojo-bench.lock` to avoid concurrent factory
jobs distorting its output.

## License

MIT
