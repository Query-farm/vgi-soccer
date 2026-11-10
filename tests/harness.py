"""In-process harness for invoking table functions without the VGI transport."""

from __future__ import annotations

import pyarrow as pa


class Collector:
    """Minimal stand-in for the SDK OutputCollector."""

    def __init__(self) -> None:
        self.batches: list[pa.RecordBatch] = []
        self.cache_controls: list[object] = []
        self.finished = False

    def emit(self, batch: pa.RecordBatch, cache_control: object = None) -> None:
        self.batches.append(batch)
        self.cache_controls.append(cache_control)

    def finish(self) -> None:
        self.finished = True

    def rows(self) -> list[dict]:
        return [row for batch in self.batches for row in batch.to_pylist()]


class Params:
    """Minimal stand-in for ProcessParams."""

    def __init__(self, args: object, output_schema: pa.Schema) -> None:
        self.args = args
        self.output_schema = output_schema


def run_function(function: type, args: object = None) -> Collector:
    """Invoke a table function's process() in-process and collect its output."""
    out = Collector()
    function.process(Params(args, function.FIXED_SCHEMA), None, out)
    assert out.finished
    return out
