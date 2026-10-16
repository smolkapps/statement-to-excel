"""Synthetic subprocess faults for deadline tests; never writes statement data.

This helper is only selected by test monkeypatches. Readiness reports contain a
PID and phase name on a loopback socket, so no fixture bytes enter test files.
"""

import os
import socket
import sys
import time


def main():
    phase, port = sys.argv[1:3]
    import statement_to_excel.conversion as conversion

    def blocked(*args, **kwargs):
        with socket.create_connection(("127.0.0.1", int(port))) as connection:
            connection.sendall(f"{os.getpid()}:{phase}\n".encode("ascii"))
        # A real uncooperative worker: cancellation of the parent's await does
        # not stop this CPU loop. Only terminating the process stops the work.
        while True:
            pass

    if phase == "no_disk":
        import tempfile
        import openpyxl.worksheet._writer as worksheet_writer

        def forbidden_disk_file(*args, **kwargs):
            raise AssertionError("Synthetic conversion attempted a temporary disk file")

        tempfile.TemporaryFile = forbidden_disk_file
        tempfile.NamedTemporaryFile = forbidden_disk_file
        worksheet_writer.NamedTemporaryFile = forbidden_disk_file
        worksheet_writer.create_temporary_file = forbidden_disk_file
    elif phase == "crash":
        # Unexpected internal errors must not leak row/statement text.
        def crash(*args, **kwargs):
            raise RuntimeError("SECRET_SYNTHETIC_STATEMENT_DESCRIPTION")

        conversion.to_xlsx_bytes = crash
    elif phase == "exit":
        os._exit(23)
    elif phase in {"oversized_output", "partial_output", "malformed_output", "stdout_flood"}:
        # Advertise more than the parent's IPC limit without allocating it.
        import json
        import struct

        if phase == "malformed_output":
            metadata = b"not valid JSON"
        else:
            metadata = json.dumps({"pages": 1, "transaction_count": 1,
                                   "media_type": "text/csv",
                                   "body_size": (2 ** 31 if phase == "oversized_output" else
                                                 0 if phase == "stdout_flood" else 8)}).encode()
        sys.stdout.buffer.write(struct.pack("!I", len(metadata)) + metadata)
        if phase == "partial_output":
            sys.stdout.buffer.write(b"x")
        sys.stdout.buffer.flush()
        if phase == "stdout_flood":
            # Fill the transport/OS pipe so cleanup must drain it after killing
            # the child; waiting for the child first can deadlock asyncio.
            sys.stdout.buffer.write(b"x" * (4 * 1024 * 1024))
            sys.stdout.buffer.flush()
        if phase == "partial_output":
            blocked()
        else:
            time.sleep(30)
        return
    elif phase == "memory":
        def allocate(*args, **kwargs):
            # The production worker must apply its memory cap before parsing.
            # Allocating this block would exceed the configured 512 MiB cap.
            return bytearray(1024 * 1024 * 1024)

        conversion.count_pages = allocate
    elif phase == "resource_guards":
        original_parse = conversion.convert_pdf

        def guarded_parse(*args, **kwargs):
            import resource
            from statement_to_excel.conversion_worker import MAX_CONVERSION_MEMORY_BYTES

            assert resource.getrlimit(resource.RLIMIT_CORE) == (0, 0)
            assert 0 < resource.getrlimit(resource.RLIMIT_AS)[0] <= MAX_CONVERSION_MEMORY_BYTES
            assert 0 < resource.getrlimit(resource.RLIMIT_CPU)[0] <= 6
            if sys.platform.startswith("linux"):
                import ctypes

                assert ctypes.CDLL(None).prctl(3, 0, 0, 0, 0) == 0  # PR_GET_DUMPABLE
            assert "statement_to_excel.api" not in sys.modules
            assert "statement_to_excel.billing" not in sys.modules
            return original_parse(*args, **kwargs)

        conversion.convert_pdf = guarded_parse
    elif phase == "json":
        conversion.json.dumps = blocked
    elif phase == "base64":
        conversion.base64.b64encode = blocked
    elif phase != "after_output":
        target = {"count": "count_pages", "parse": "convert_pdf",
                  "csv": "to_csv_bytes", "xlsx": "to_xlsx_bytes"}[phase]
        setattr(conversion, target, blocked)

    from statement_to_excel.conversion_worker import main as run_worker

    run_worker()
    if phase == "after_output":
        # A complete artifact does not authorize billing while the worker is
        # still running and holding document memory or IPC descriptors.
        blocked()


if __name__ == "__main__":
    main()
