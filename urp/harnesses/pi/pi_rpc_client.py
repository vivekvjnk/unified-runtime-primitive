import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Union

from .rpc_types import (
    ExtensionUiRequest,
    ExtensionUiResponse,
    PiRpcCommandError,
    PiRpcConnectionError,
    PiRpcError,
    PiRpcProcessTerminatedError,
    PiRpcTimeoutError,
    RpcCommand,
    RpcEvent,
    RpcResponse,
)

logger = logging.getLogger("urp.pi_rpc_client")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

UIHandlerCallable = Callable[[ExtensionUiRequest], Union[ExtensionUiResponse, Coroutine[Any, Any, ExtensionUiResponse]]]
EventHandlerCallable = Callable[[RpcEvent], None]


class PiRpcClient:
    """
    Python async client wrapper for the 'pi' agent harness running in RPC mode (`pi --mode rpc`).
    
    Manages subprocess lifecycle, strict JSONL transport over stdio, command/response matching,
    streaming event propagation, and extension UI sub-protocol requests.
    """

    def __init__(
        self,
        workspace_dir: Union[str, Path],
        model: Optional[str] = None,
        provider: Optional[str] = None,
        session_dir: Optional[Union[str, Path]] = None,
        no_session: bool = False,
        system_prompt: Optional[str] = None,
        name: Optional[str] = None,
        extra_args: Optional[List[str]] = None,
        env: Optional[Dict[str, str]] = None,
        executable_path: str = "pi",
    ):
        self.workspace_dir = Path(workspace_dir).resolve()
        self.model = model
        self.provider = provider
        self.session_dir = Path(session_dir).resolve() if session_dir else None
        self.no_session = no_session
        self.system_prompt = system_prompt
        self.name = name
        self.extra_args = extra_args or []
        self.env = env
        self.executable_path = executable_path

        self._process: Optional[asyncio.subprocess.Process] = None
        self._pending_commands: Dict[str, asyncio.Future[RpcResponse]] = {}
        self._event_handlers: Dict[str, List[EventHandlerCallable]] = {}
        self._any_event_handlers: List[EventHandlerCallable] = []
        self._ui_handler: Optional[UIHandlerCallable] = None

        self._stdout_task: Optional[asyncio.Task] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr_buffer: List[str] = []
        self._is_closing: bool = False

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    async def start(self) -> None:
        """Spawns the `pi --mode rpc` subprocess and starts reading stdio streams."""
        if self.is_running:
            logger.warning("PiRpcClient is already running.")
            return

        if self.executable_path.endswith(".py"):
            cmd = [sys.executable, self.executable_path, "--mode", "rpc"]
        else:
            cmd = [self.executable_path, "--mode", "rpc"]

        if self.no_session:
            cmd.append("--no-session")
        elif self.session_dir:
            cmd.extend(["--session-dir", str(self.session_dir)])

        if self.provider:
            cmd.extend(["--provider", self.provider])
        if self.model:
            cmd.extend(["--model", self.model])
        if self.name:
            cmd.extend(["--name", self.name])

        cmd.extend(self.extra_args)

        proc_env = os.environ.copy()
        if self.env:
            proc_env.update(self.env)

        logger.info(f"Spawning pi RPC process: {' '.join(cmd)} in cwd={self.workspace_dir}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.workspace_dir),
                env=proc_env,
            )
        except Exception as e:
            logger.error(f"Failed to spawn pi RPC process: {e}")
            raise PiRpcConnectionError(f"Failed to spawn pi process: {e}") from e

        self._is_closing = False
        self._stdout_task = asyncio.create_task(self._read_stdout_loop())
        self._stderr_task = asyncio.create_task(self._read_stderr_loop())

    async def close(self) -> None:
        """Gracefully shuts down the subprocess and terminates background tasks."""
        if self._is_closing:
            return
        self._is_closing = True

        logger.info("Closing PiRpcClient connection...")

        # Fail any pending command futures
        for req_id, fut in list(self._pending_commands.items()):
            if not fut.done():
                fut.set_exception(PiRpcProcessTerminatedError("PiRpcClient closed while command was pending."))
        self._pending_commands.clear()

        if self._process and self._process.returncode is None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
                    await self._process.stdin.wait_closed()
            except Exception:
                pass

            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except asyncio.TimeoutError:
                logger.warning("pi process did not terminate within timeout, killing...")
                self._process.kill()
                await self._process.wait()
            except Exception as e:
                logger.error(f"Error terminating pi process: {e}")

        for t in (self._stdout_task, self._stderr_task):
            if t and not t.done():
                t.cancel()
                try:
                    await t
                except asyncio.CancelledError:
                    pass

        self._process = None
        logger.info("PiRpcClient closed successfully.")

    # ---------------------------------------------------------
    # JSONL Transport Reader Loops
    # ---------------------------------------------------------

    async def _read_stdout_loop(self) -> None:
        """Reads JSONL records line-by-line from stdout."""
        if not self._process or not self._process.stdout:
            return

        buffer = ""
        while self.is_running and not self._is_closing:
            try:
                chunk = await self._process.stdout.read(4096)
                if not chunk:
                    logger.info("pi stdout stream EOF reached.")
                    break

                buffer += chunk.decode("utf-8", errors="replace")

                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    if line.endswith("\r"):
                        line = line[:-1]
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)
                        await self._handle_incoming_line(data)
                    except json.JSONDecodeError as je:
                        logger.error(f"JSON parse error on pi stdout line: {line} - Error: {je}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error reading pi stdout: {e}")
                break

        if not self._is_closing:
            logger.warning("Stdout loop exited while client was active. Process may have exited.")
            await self._on_process_exit()

    async def _read_stderr_loop(self) -> None:
        """Reads lines from stderr for error logging."""
        if not self._process or not self._process.stderr:
            return

        while self.is_running and not self._is_closing:
            try:
                line = await self._process.stderr.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").rstrip()
                if decoded:
                    self._stderr_buffer.append(decoded)
                    logger.warning(f"[pi stderr] {decoded}")
            except asyncio.CancelledError:
                break
            except Exception:
                break

    async def _on_process_exit(self) -> None:
        """Called when subprocess unexpectedly exits."""
        stderr_text = "\n".join(self._stderr_buffer[-20:])
        err_msg = f"pi RPC process terminated unexpectedly. Stderr:\n{stderr_text}"
        logger.error(err_msg)

        for req_id, fut in list(self._pending_commands.items()):
            if not fut.done():
                fut.set_exception(PiRpcProcessTerminatedError(err_msg))
        self._pending_commands.clear()

    async def _handle_incoming_line(self, data: Dict[str, Any]) -> None:
        """Routes parsed stdout JSON objects."""
        msg_type = data.get("type")

        # 1. Command Response
        if msg_type == "response":
            response = RpcResponse.from_dict(data)
            req_id = response.id
            if req_id and req_id in self._pending_commands:
                fut = self._pending_commands.pop(req_id)
                if not fut.done():
                    fut.set_result(response)
            else:
                logger.debug(f"Received response for untracked or timed-out request id: {req_id}")

        # 2. Extension UI Sub-protocol Request
        elif msg_type == "extension_ui_request":
            req = ExtensionUiRequest.from_dict(data)
            await self._dispatch_ui_request(req)

        # 3. Streamed Event
        else:
            event = RpcEvent.from_dict(data)
            self._dispatch_event(event)

    # ---------------------------------------------------------
    # Event Dispatching & Handlers
    # ---------------------------------------------------------

    def on_event(self, event_type: str, handler: EventHandlerCallable) -> None:
        """Registers a listener for a specific event type."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def on_any_event(self, handler: EventHandlerCallable) -> None:
        """Registers a wildcard listener for all events."""
        self._any_event_handlers.append(handler)

    def register_ui_handler(self, handler: UIHandlerCallable) -> None:
        """Registers a custom Extension UI handler."""
        self._ui_handler = handler

    def _dispatch_event(self, event: RpcEvent) -> None:
        """Invokes registered event handlers."""
        for handler in self._any_event_handlers:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Error in wildcard event handler: {e}")

        if event.type in self._event_handlers:
            for handler in self._event_handlers[event.type]:
                try:
                    handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler for {event.type}: {e}")

    async def _dispatch_ui_request(self, req: ExtensionUiRequest) -> None:
        """Handles Extension UI dialog requests and transmits stdin response."""
        response: Optional[ExtensionUiResponse] = None

        if self._ui_handler:
            try:
                res = self._ui_handler(req)
                if asyncio.iscoroutine(res):
                    response = await res
                else:
                    response = res  # type: ignore
            except Exception as e:
                logger.error(f"Error in Extension UI handler: {e}")

        if response is None:
            if req.method == "confirm":
                response = ExtensionUiResponse(id=req.id, confirmed=True)
            elif req.method in ("select", "input", "editor"):
                val = req.options[0] if req.options else ""
                response = ExtensionUiResponse(id=req.id, value=val)
            else:
                response = ExtensionUiResponse(id=req.id, cancelled=False)

        if response:
            await self._send_raw_json(response.to_dict())

    # ---------------------------------------------------------
    # Command Delivery Primaries
    # ---------------------------------------------------------

    async def _send_raw_json(self, payload: Dict[str, Any]) -> None:
        """Writes a single JSON line to stdin."""
        if not self.is_running or not self._process or not self._process.stdin:
            raise PiRpcConnectionError("Cannot send command: pi RPC subprocess is not running.")

        line = json.dumps(payload) + "\n"
        try:
            self._process.stdin.write(line.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            logger.error(f"Failed writing line to pi stdin: {e}")
            raise PiRpcConnectionError(f"Write to pi stdin failed: {e}") from e

    async def send_command(
        self,
        command: Union[Dict[str, Any], RpcCommand],
        timeout: float = 30.0,
    ) -> RpcResponse:
        """Sends a JSON command over stdin and awaits matching response by id."""
        if not self.is_running:
            raise PiRpcConnectionError("pi RPC client is not running. Call start() first.")

        if isinstance(command, RpcCommand):
            payload = command.to_dict()
        else:
            payload = dict(command)

        req_id = payload.get("id") or f"req-{uuid.uuid4().hex[:8]}"
        payload["id"] = req_id

        fut: asyncio.Future[RpcResponse] = asyncio.get_running_loop().create_future()
        self._pending_commands[req_id] = fut

        try:
            await self._send_raw_json(payload)
            response = await asyncio.wait_for(fut, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            self._pending_commands.pop(req_id, None)
            logger.error(f"Command '{payload.get('type')}' (id={req_id}) timed out after {timeout}s")
            raise PiRpcTimeoutError(f"Command '{payload.get('type')}' timed out after {timeout} seconds.")
        except Exception:
            self._pending_commands.pop(req_id, None)
            raise

    # ---------------------------------------------------------
    # Helper Command Wrappers
    # ---------------------------------------------------------

    async def send_prompt(
        self,
        message: str,
        streaming_behavior: Optional[str] = None,
        images: Optional[List[Dict[str, Any]]] = None,
        timeout: float = 120.0,
    ) -> RpcResponse:
        """Sends a user prompt to the agent."""
        payload: Dict[str, Any] = {
            "type": "prompt",
            "message": message,
        }
        if streaming_behavior:
            payload["streamingBehavior"] = streaming_behavior
        if images:
            payload["images"] = images

        return await self.send_command(payload, timeout=timeout)

    async def steer(self, message: str, images: Optional[List[Dict[str, Any]]] = None) -> RpcResponse:
        """Queues a steering message."""
        payload: Dict[str, Any] = {"type": "steer", "message": message}
        if images:
            payload["images"] = images
        return await self.send_command(payload)

    async def follow_up(self, message: str, images: Optional[List[Dict[str, Any]]] = None) -> RpcResponse:
        """Queues a follow-up message."""
        payload: Dict[str, Any] = {"type": "follow_up", "message": message}
        if images:
            payload["images"] = images
        return await self.send_command(payload)

    async def abort(self) -> RpcResponse:
        """Aborts current agent execution."""
        return await self.send_command({"type": "abort"})

    async def bash(self, command: str, req_id: Optional[str] = None, timeout: float = 60.0) -> RpcResponse:
        """Executes a shell command directly via RPC bash."""
        payload: Dict[str, Any] = {"type": "bash", "command": command}
        if req_id:
            payload["id"] = req_id
        return await self.send_command(payload, timeout=timeout)

    async def get_state(self) -> RpcResponse:
        """Queries current session state."""
        return await self.send_command({"type": "get_state"})

    async def get_messages(self) -> RpcResponse:
        """Fetches all conversation messages."""
        return await self.send_command({"type": "get_messages"})

    async def get_last_assistant_text(self) -> RpcResponse:
        """Fetches the last assistant response text."""
        return await self.send_command({"type": "get_last_assistant_text"})

    async def get_available_models(self) -> RpcResponse:
        """Lists available models."""
        return await self.send_command({"type": "get_available_models"})

    async def set_model(self, provider: str, model_id: str) -> RpcResponse:
        """Switches current model."""
        return await self.send_command({
            "type": "set_model",
            "provider": provider,
            "modelId": model_id,
        })

    async def cycle_model(self) -> RpcResponse:
        """Cycles to the next available model."""
        return await self.send_command({"type": "cycle_model"})

    async def set_thinking_level(self, level: str) -> RpcResponse:
        """Sets thinking/reasoning effort level ('off', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')."""
        return await self.send_command({"type": "set_thinking_level", "level": level})

    async def get_available_thinking_levels(self) -> RpcResponse:
        """Gets available thinking levels for the current model."""
        return await self.send_command({"type": "get_available_thinking_levels"})

    async def set_auto_compaction(self, enabled: bool) -> RpcResponse:
        """Enables or disables automatic context compaction."""
        return await self.send_command({"type": "set_auto_compaction", "enabled": enabled})

    async def set_auto_retry(self, enabled: bool) -> RpcResponse:
        """Enables or disables automatic retry on transient errors."""
        return await self.send_command({"type": "set_auto_retry", "enabled": enabled})

    async def compact(self, custom_instructions: Optional[str] = None) -> RpcResponse:
        """Triggers context compaction."""
        payload: Dict[str, Any] = {"type": "compact"}
        if custom_instructions:
            payload["customInstructions"] = custom_instructions
        return await self.send_command(payload, timeout=90.0)

    async def get_session_stats(self) -> RpcResponse:
        """Gets token and context stats."""
        return await self.send_command({"type": "get_session_stats"})

    async def new_session(self, parent_session: Optional[str] = None) -> RpcResponse:
        """Starts a fresh session."""
        payload: Dict[str, Any] = {"type": "new_session"}
        if parent_session:
            payload["parentSession"] = parent_session
        return await self.send_command(payload)
