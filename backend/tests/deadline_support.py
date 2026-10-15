"""Real subprocess probes shared by deadline, health and upload cleanup tests."""

import asyncio
import sys

import statement_to_excel.conversion_timeout as deadline


class WorkerProbe:
    def __init__(self, monkeypatch, phase, *, timeout=1.5):
        self.monkeypatch = monkeypatch
        self.phase = phase
        self.timeout = timeout
        self.processes = []
        self.ready = asyncio.Queue()

    async def __aenter__(self):
        async def receive(reader, writer):
            try:
                message = (await reader.readline()).decode("ascii").strip()
                pid, phase = message.split(":", 1)
                self.ready.put_nowait((int(pid), phase))
            finally:
                writer.close()
                await writer.wait_closed()

        self.server = await asyncio.start_server(receive, "127.0.0.1", 0)
        port = self.server.sockets[0].getsockname()[1]
        self.monkeypatch.setattr(deadline, "CONVERSION_TIMEOUT_SECONDS", self.timeout)
        self.monkeypatch.setattr(deadline, "_worker_command", lambda: [
            sys.executable, "-m", "tests.deadline_worker", self.phase, str(port),
        ])
        original = asyncio.create_subprocess_exec

        async def track_process(*args, **kwargs):
            process = await original(*args, **kwargs)
            self.processes.append(process)
            return process

        self.monkeypatch.setattr(asyncio, "create_subprocess_exec", track_process)
        return self

    async def wait_entered(self):
        pid, phase = await asyncio.wait_for(self.ready.get(), timeout=10)
        assert phase == self.phase
        assert any(process.pid == pid for process in self.processes)
        return pid

    def assert_reaped(self):
        assert self.processes, "the test must launch an actual conversion subprocess"
        for process in self.processes:
            assert process.returncode is not None, "worker must exit before request completion"
            # waitpid, unlike polling process state alone, proves the child is
            # already reaped and cannot accumulate as a zombie in the API.
            import os

            try:
                os.waitpid(process.pid, os.WNOHANG)
            except ChildProcessError:
                pass
            else:
                raise AssertionError("conversion child was not already reaped")

    async def __aexit__(self, *exc):
        self.server.close()
        await self.server.wait_closed()
