"""One disposable conversion process. PDFs, worksheet XML and IPC stay in memory.

This module must not import the API, a ledger or a payment provider.
"""

from __future__ import annotations

import io
import json
import math
import os
import struct
import sys

from .conversion import MAX_UPLOAD_BYTES, ConversionRejected, prepare_conversion

MAX_HEADER_BYTES = 4096
MAX_CONVERSION_MEMORY_BYTES = 512 * 1024 * 1024
WORKER_ERROR = "Conversion could not be completed. Please try again with a smaller statement."


def _resource_limits(timeout: float) -> None:
    # No statement contents may enter a crash/core file. The wall-clock watchdog
    # in the parent remains authoritative; CPU/address-space limits are backstops.
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if sys.platform.startswith("linux"):
        # Linux piped core collectors can ignore RLIMIT_CORE. Disable dumpability
        # as well, before reading any PDF bytes; fail closed if this is denied.
        import ctypes
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(4, 0, 0, 0, 0) != 0:  # PR_SET_DUMPABLE
            raise OSError(ctypes.get_errno(), "Could not disable worker core dumps")
    for resource_id, limit in ((resource.RLIMIT_AS, MAX_CONVERSION_MEMORY_BYTES),
                               (resource.RLIMIT_CPU, max(1, math.ceil(timeout) + 1))):
        _, hard = resource.getrlimit(resource_id)
        if hard != resource.RLIM_INFINITY:
            limit = min(limit, hard)
        resource.setrlimit(resource_id, (limit, limit))


def _write_result(output, metadata: dict, body: bytes = b"") -> None:
    header = json.dumps(metadata, separators=(",", ":")).encode("utf-8")
    if len(header) > MAX_HEADER_BYTES:
        raise ValueError("Invalid worker response")
    output.write(struct.pack("!I", len(header)))
    output.write(header)
    output.write(body)
    output.flush()


def main() -> None:
    output = sys.stdout.buffer
    # Libraries must not accidentally put extracted text into response framing
    # or service logs. Keep only the dedicated binary protocol stream.
    sys.stdout = io.TextIOWrapper(open(os.devnull, "wb"), encoding="utf-8")
    try:
        length = struct.unpack("!I", sys.stdin.buffer.read(4))[0]
        if not 0 < length <= MAX_HEADER_BYTES:
            raise ValueError("Invalid worker request")
        options = json.loads(sys.stdin.buffer.read(length))
        _resource_limits(float(options["timeout"]))
        data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise ConversionRejected(413, "PDF uploads are limited to 20 MiB")
        artifact = prepare_conversion(data, options["fmt"], options["currency"], options["preview"])
        _write_result(output, {"pages": artifact.pages, "transaction_count": artifact.transaction_count,
                               "media_type": artifact.media_type, "body_size": len(artifact.body)}, artifact.body)
    except ConversionRejected as exc:
        _write_result(output, {"status_code": exc.status_code, "detail": exc.detail})
    except BaseException:
        # Never serialize traceback, exception arguments, input bytes or paths.
        _write_result(output, {"status_code": 500, "detail": WORKER_ERROR})


if __name__ == "__main__":
    main()
