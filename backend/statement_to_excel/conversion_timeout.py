"""Bounded, killable conversion with capped concurrency and framed memory IPC."""

from __future__ import annotations

import asyncio
import json
import math
import os
import signal
import struct
import sys
import threading

from anyio import CancelScope

from .conversion import MAX_OUTPUT_BYTES, MAX_STATEMENT_PAGES, ConversionArtifact, ConversionRejected


def _deadline_setting() -> float:
    value = float(os.getenv("STX_CONVERSION_TIMEOUT_SECONDS", "30"))
    if not math.isfinite(value) or not 0 < value <= 120:
        raise ValueError("STX_CONVERSION_TIMEOUT_SECONDS must be greater than 0 and at most 120")
    return value


CONVERSION_TIMEOUT_SECONDS = _deadline_setting()
MAX_CONCURRENT_CONVERSIONS = 2  # Per ASGI worker; no queue retaining uploaded PDFs.
MAX_HEADER_BYTES = 4096
_slots = threading.BoundedSemaphore(MAX_CONCURRENT_CONVERSIONS)


class ConversionTimeout(ConversionRejected):
    def __init__(self):
        super().__init__(504, "Conversion took too long. Please try again with a smaller statement or split it into fewer pages.")


class ConversionBusy(ConversionRejected):
    def __init__(self):
        super().__init__(503, "Conversion is busy. Please try again shortly.")


class ConversionWorkerError(ConversionRejected):
    def __init__(self):
        super().__init__(500, "Conversion could not be completed. Please try again with a smaller statement.")


def _worker_command() -> list[str]:
    return [sys.executable, "-m", "statement_to_excel.conversion_worker"]


async def _cleanup(process, sender) -> None:
    if process is not None:
        # Kill the whole disposable session, including any descendants holding
        # pipe descriptors. Do not release capacity until the child is reaped.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if sender is not None:
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
    if process is not None:
        process.stdin.close()
        # Process.wait alone can deadlock when a killed worker filled stdout's
        # flow-controlled pipe. Discard remaining bytes in bounded chunks first.
        while await process.stdout.read(65536):
            pass
        await process.wait()


async def run_conversion(data: bytes, fmt: str, currency: str, preview: bool) -> ConversionArtifact:
    """Deadline includes child startup, every PDF/output phase, IPC and exit.

    Cancellation/timeout kills and reaps the worker before returning or freeing
    its slot. No uncontrolled background worker or billing call survives it.
    """
    if not _slots.acquire(blocking=False):
        raise ConversionBusy()
    process = None
    sender = None
    cancelled_during_cleanup = False
    try:
        async def exchange():
            nonlocal process, sender
            options = json.dumps({"fmt": fmt, "currency": currency, "preview": preview,
                                  "timeout": CONVERSION_TIMEOUT_SECONDS}).encode("utf-8")
            if len(options) > MAX_HEADER_BYTES:
                raise ConversionRejected(400, "Conversion options are too large")
            process = await asyncio.create_subprocess_exec(
                *_worker_command(), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )

            async def send():
                try:
                    process.stdin.write(struct.pack("!I", len(options)) + options)
                    for offset in range(0, len(data), 65536):
                        process.stdin.write(data[offset:offset + 65536])
                        await process.stdin.drain()
                    process.stdin.close()
                    await process.stdin.wait_closed()
                except (BrokenPipeError, ConnectionResetError):
                    # A crashed worker is handled by missing/invalid framing.
                    pass
            sender = asyncio.create_task(send())
            size = struct.unpack("!I", await process.stdout.readexactly(4))[0]
            if not 0 < size <= MAX_HEADER_BYTES:
                raise ConversionWorkerError()
            header = json.loads(await process.stdout.readexactly(size))
            if "status_code" in header:
                if header["status_code"] not in (400, 413, 422, 500) \
                        or not isinstance(header.get("detail"), str):
                    raise ConversionWorkerError()
                await sender
                if await process.stdout.read(1) or await process.wait() != 0:
                    raise ConversionWorkerError()
                raise ConversionRejected(header["status_code"], header["detail"])
            length = header["body_size"]
            if type(length) is not int or not 0 <= length <= MAX_OUTPUT_BYTES:
                raise ConversionWorkerError()
            pages, count = header["pages"], header["transaction_count"]
            if type(pages) is not int or not 1 <= pages <= MAX_STATEMENT_PAGES \
                    or type(count) is not int or count < 0 \
                    or header["media_type"] not in ("application/json", "text/csv",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"):
                raise ConversionWorkerError()
            body = await process.stdout.readexactly(length)
            await sender
            if await process.stdout.read(1) or await process.wait() != 0:
                raise ConversionWorkerError()
            return ConversionArtifact(pages, count, body, header["media_type"])

        try:
            return await asyncio.wait_for(exchange(), timeout=CONVERSION_TIMEOUT_SECONDS)
        except asyncio.TimeoutError as exc:
            raise ConversionTimeout() from exc
        except ConversionRejected:
            raise
        except (OSError, ValueError, KeyError, TypeError, asyncio.IncompleteReadError) as exc:
            raise ConversionWorkerError() from exc
    finally:
        # AnyIO level cancellation and direct asyncio Task.cancel() both must
        # wait for kill/reap rather than orphaning statement processing.
        with CancelScope(shield=True):
            cleanup = asyncio.create_task(_cleanup(process, sender))
            try:
                while True:
                    try:
                        await asyncio.shield(cleanup)
                        break
                    except asyncio.CancelledError:
                        cancelled_during_cleanup = True
            finally:
                _slots.release()
        if cancelled_during_cleanup:
            raise asyncio.CancelledError
