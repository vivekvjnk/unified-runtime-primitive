import logging
import asyncio

import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, Optional
from .data_types import AgentDescriptor, AgentContext, AgentState, MessageEnvelope, LastTaskOutcome, AgentStatus, ProcessResult, FailureCategory

# Standard logger setup for standalone URP
logger = logging.getLogger("urp.abstract_urp")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

MAILBOX_POLL_INTERVAL = 0.5  # seconds

class PostconditionsViolatedError(Exception):
    """Raised when post-condition verification fails."""
    def __init__(self,result,message):
        """
        result: Agent execution result
        message: Error message
        """
        self.result = result
        super().__init__(message)

class PreconditionsViolatedError(Exception):
    """Raised when pre-condition verification fails."""
    pass

class StartPreconditionsViolatedError(Exception):
    """Raised when agent start precondition verification fails."""
    pass

class AbstractURPAgent(ABC):
    """
    Abstract Unified Runtime Primitive (URP).
    Enforces the lifecycle, mailbox, and state invariants.
    """

    def __init__(self, descriptor: 'AgentDescriptor'):
        # 1. Addressable Identity
        self.descriptor = descriptor
        
        # 3. Persistent State (initialized to baseline)
        self._state = AgentState(
            session_id=str(uuid.uuid4()), 
            status=AgentStatus.UNINITIALIZED
        )
        
        # 4. Mailbox
        self.mailbox: asyncio.Queue['MessageEnvelope'] = asyncio.Queue()
        
        # Internal Runtime hooks
        self.context: Optional['AgentContext'] = None
        self._emit_callback: Optional[Callable[['MessageEnvelope'], None]] = None
        self._shutdown_event = asyncio.Event()
        self._task: Optional[asyncio.Task] = None
        self._current_message: Optional['MessageEnvelope'] = None
        
        logger.info(f"[{self.descriptor.agent_id}] AbstractURPAgent instantiated. Session ID: {self._state.session_id}")

    # ---------------------------------------------------------
    # LIFECYCLE CONTRACT (URP Section 4)
    # ---------------------------------------------------------

    def initialize(self, context, emit_callback: Callable[['MessageEnvelope'], None]) -> None:
        """Runs exactly once. Binds dependencies and event bus."""
        # Invariant 1: Initialize exactly once
        if self._state.status != AgentStatus.UNINITIALIZED:
            logger.error(f"[{self.descriptor.agent_id}] Initialization failed: Agent is already in state {self._state.status}")
            raise RuntimeError(f"Cannot initialize agent in state: {self._state.status}")
        
        logger.info(f"[{self.descriptor.agent_id}] Initializing agent...")
        self.context = context
        self.set_callback(emit_callback)
        
        # Allow child classes to perform specific initialization (e.g., loading prompts)
        self._on_initialize(context)
        
        self._state.status = AgentStatus.INITIALIZED
        logger.info(f"[{self.descriptor.agent_id}] Agent successfully transitioned to state: {self._state.status}")
    
    def set_callback(self,emit_callback: Callable[['MessageEnvelope'], None]) -> None:
        """Allows resetting the emit callback, useful for testing or dynamic rebinding."""
        logger.debug(f"[{self.descriptor.agent_id}] Setting new emit callback.")
        self._emit_callback = emit_callback

    async def start(self) -> None:
        """Makes agent runnable. Enters WAITING state."""
        if self._state.status != AgentStatus.INITIALIZED:
            logger.error(f"[{self.descriptor.agent_id}] Start failed: Agent must be INITIALIZED. Current: {self._state.status}")
            raise RuntimeError(f"Agent must be INITIALIZED to start. Current: {self._state.status}")
        
        logger.info(f"[{self.descriptor.agent_id}] Verifying start preconditions...")
        # Check start preconditions
        start_ok, result = await self._check_start_preconditions()
            
        if not start_ok:
            logger.warning(f"[{self.descriptor.agent_id}] Start preconditions violated: {result}")
            await self.emit(MessageEnvelope(
                type="AGENT_START_PRECONDITIONS_VIOLATED",
                payload={"reason": result,"text": result},
                sender=self.descriptor.agent_id
            ))
            raise StartPreconditionsViolatedError(f"Start preconditions check failed: {result}")
            
        self._state.status = AgentStatus.WAITING
        self._state.last_process_result = ProcessResult(outcome=LastTaskOutcome.NONE, category=FailureCategory.NONE)
        self._task = asyncio.create_task(self._lifecycle_loop())
        
        logger.info(f"[{self.descriptor.agent_id}] Lifecycle loop spawned successfully. Status: {self._state.status}")
        await self.emit(MessageEnvelope(
            type="AGENT_STARTED",
            payload={"session_id": self._state.session_id, "text": "Agent has started successfully."},
            sender=self.descriptor.agent_id
        ))

    async def send(self, message: 'MessageEnvelope') -> None:
        """Asynchronous mailbox delivery. Invariant 3: Messages enter only through mailbox."""
        if self._state.status == AgentStatus.TERMINATED:
            logger.error(f"[{self.descriptor.agent_id}] Drop Message Alert: Cannot send message to a terminating/terminated agent. Msg ID: {message.message_id}")
            raise RuntimeError("Cannot send message to a terminating/terminated agent.")
            
        logger.debug(f"[{self.descriptor.agent_id}] Enqueueing message into mailbox. Msg ID: {message.message_id}. Type: {message.type}")
        await self.mailbox.put(message)

    async def emit(self, event: 'MessageEnvelope') -> None:
        """Pushes output to runtime bus. Invariant 4: Outputs leave only through emit."""
        if self._emit_callback:
            logger.debug(f"[{self.descriptor.agent_id}] Emitting event of type '{event.type}' to runtime bus.")
            res = self._emit_callback(event)
            if res is not None and asyncio.iscoroutine(res):
                await res
        else:
            logger.warning(f"[{self.descriptor.agent_id}] Event emitted but no callback is bound. Event Type: {event.type}")

    @property
    def is_streaming(self) -> bool:
        """Returns True if the current active message envelope requested streaming."""
        return bool(self._current_message and self._current_message.streaming)

    async def emit_chunk(
        self,
        chunk: Any,
        event_type: str = "TEXT_DELTA",
        task_id: Optional[str] = None,
        context_id: Optional[str] = None,
    ) -> None:
        """
        Emits an in-flight streaming chunk to the runtime bus ONLY IF streaming is requested
        on the active message envelope.
        """
        if not self.is_streaming:
            return

        active_msg = self._current_message
        tid = task_id or (active_msg.task_id if active_msg else None)
        cid = context_id or (active_msg.context_id if active_msg else None)
        corr_id = active_msg.correlation_id if active_msg else None

        payload: Any
        if isinstance(chunk, str):
            payload = {"text": chunk, "delta": chunk}
        elif isinstance(chunk, dict):
            payload = chunk
        else:
            payload = {"data": chunk}

        chunk_env = MessageEnvelope(
            type=event_type,
            payload=payload,
            sender=self.descriptor.agent_id,
            context_id=cid,
            task_id=tid,
            correlation_id=corr_id,
        )
        await self.emit(chunk_env)

    async def shutdown(self) -> None:
        """Graceful termination."""
        logger.info(f"[{self.descriptor.agent_id}] Triggering graceful shutdown...")
        self._shutdown_event.set()
        
        # Allow child classes to clean up resources
        await self._on_shutdown()
        
        if self._task:
            logger.debug(f"[{self.descriptor.agent_id}] Awaiting lifecycle loop task completion.")
            await self._task
            
        self._state.status = AgentStatus.TERMINATED
        logger.info(f"[{self.descriptor.agent_id}] Agent has safely terminated. Final status: {self._state.status}")
        
        await self.emit(MessageEnvelope(
            type="AGENT_TERMINATED",
            payload={   "text": "Agent has terminated successfully."},
            sender=self.descriptor.agent_id
        ))

    # ---------------------------------------------------------
    # SCHEDULER CONTRACT (URP Section 5)
    # ---------------------------------------------------------

    async def _lifecycle_loop(self) -> None:
        """
        The mandated single invariant loop:
        WAITING -> receive message -> PROCESSING -> emit events -> WAITING
        """
        logger.info(f"[{self.descriptor.agent_id}] Entering core lifecycle execution loop.")
        while not self._shutdown_event.is_set():
            try:
                # 1. WAITING
                self._state.status = AgentStatus.WAITING

                # 0.5s timeout to check mailbox periodically. If no messages, loop continues.
                message = await asyncio.wait_for(self.mailbox.get(), timeout=MAILBOX_POLL_INTERVAL)
                
                logger.info(f"[{self.descriptor.agent_id}] Message popped from mailbox. Processing Msg ID: {message.message_id}, Type: {message.type}, Correlation ID: {message.correlation_id}")

                try:
                    # Pre-condition Check: After a message is popped from the mailbox, call _check_preconditions.
                    logger.info(f"[{self.descriptor.agent_id}] Evaluating task preconditions for Msg ID: {message.message_id}")
                    pre_ok, pre_response = await self._check_preconditions(message)
                    
                    # If it returns False, do not transition to PROCESSING.
                    # Instead, emit an event of type TASK_PRECONDITIONS_VIOLATED, mark the task as done, and return the agent to the WAITING loop.
                    if not pre_ok:
                        raise PreconditionsViolatedError(pre_response)
                    
                    # 2. PROCESSING
                    self._state.status = AgentStatus.PROCESSING
                    self._current_message = message
                    logger.info(f"[{self.descriptor.agent_id}] Preconditions passed. Status changed to: {self._state.status}")
                    
                    # Capture the return value from the implementation
                    result: ProcessResult = await self.process(message)
                    
                    # Post-condition Check: Inside the successful block of process(), right before emitting TASK_COMPLETED, invoke _check_postconditions.
                    logger.info(f"[{self.descriptor.agent_id}] Evaluating task postconditions for Msg ID: {message.message_id}")
                    post_ok, post_response = await self._check_postconditions(message, result) 
                    # NOTE: _check_postconditions may update result.category if any categorical post condition failure occur. 

                    if not post_ok:
                        raise PostconditionsViolatedError(result=result, message=post_response)
                    
                    self._state.last_process_result = result
                    
                    logger.info(f"[{self.descriptor.agent_id}] Task processing successful. Outcome: {result.outcome}. Dispatching response.")
                    # 3. AUTO-EMIT FINAL RESULT
                    await self.emit(MessageEnvelope(
                        type=self._state.last_process_result.outcome.value,
                        payload=self._state.last_process_result,
                        sender=self.descriptor.agent_id,
                        correlation_id=message.correlation_id,
                        message_id=message.message_id
                    ))
                        
                except PostconditionsViolatedError as e:
                    logger.warning(f"[{self.descriptor.agent_id}] Postconditions violated for Msg ID {message.message_id}: {str(e)}")
                    # Post conditions validation may have already updated the FailureCategory in e.result.
                    cat = FailureCategory.POSTCONDITION_FAILURE
                    if e.result and e.result.category is not FailureCategory.NONE:
                        cat = e.result.category
                        
                    self._state.last_process_result = ProcessResult(
                        outcome=e.result.outcome, # NOTE DO NOT override outcome produced by process()
                        category=cat,
                        payload=e.result.payload
                    )
                    
                    await self.emit(MessageEnvelope(
                        type="TASK_POSTCONDITIONS_VIOLATED",
                        payload=self._state.last_process_result,
                        sender=self.descriptor.agent_id,
                        message_id=message.message_id,
                        correlation_id=message.correlation_id
                    ))
                except PreconditionsViolatedError as e:
                    logger.warning(f"[{self.descriptor.agent_id}] Preconditions violated for Msg ID {message.message_id}: {str(e)}")
                    self._state.last_process_result = ProcessResult(
                        outcome=LastTaskOutcome.TASK_FAILED,
                        category=FailureCategory.PRECONDITION_FAILURE
                    )
                    await self.emit(MessageEnvelope(
                        type="TASK_PRECONDITIONS_VIOLATED",
                        payload=self._state.last_process_result,
                        sender=self.descriptor.agent_id,
                        message_id=message.message_id,
                        correlation_id=message.correlation_id
                    ))

                except Exception as e:
                    logger.error(f"[{self.descriptor.agent_id}] Unhandled exception during processing of Msg ID {message.message_id}", exc_info=True)
                    self._state.last_process_result = ProcessResult(
                        outcome=LastTaskOutcome.TASK_FAILED,
                        category=FailureCategory.INFRASTRUCTURE_FAILURE
                    )
                    await self.emit(MessageEnvelope(
                        type="TASK_FAILED",
                        payload=self._state.last_process_result,
                        sender=self.descriptor.agent_id,
                        message_id=message.message_id,
                        correlation_id=message.correlation_id
                    ))
                finally:
                    logger.debug(f"[{self.descriptor.agent_id}] Marking mailbox task done for Msg ID: {message.message_id}")
                    self._current_message = None
                    self.mailbox.task_done()
                    
            except asyncio.TimeoutError:
                # Normal behavior when mailbox is empty during the poll interval
                continue
            except asyncio.CancelledError:
                logger.info(f"[{self.descriptor.agent_id}] Lifecycle loop received Cancellation request. Exiting loop.")
                break
            except Exception as e:
                logger.critical(f"[{self.descriptor.agent_id}] Panic: Critical failure in outer scheduler runtime loop: {str(e)}", exc_info=True)


    # ---------------------------------------------------------
    # ABSTRACT METHODS (To be implemented by specific agents)
    # ---------------------------------------------------------

    @abstractmethod
    async def process(self, message: 'MessageEnvelope') -> ProcessResult:
        """
        Core execution primitive.
        Must invoke LLM, tools, mutate state, and emit events without violating invariants.
        """
        pass

    @abstractmethod
    def _on_initialize(self, context) -> None:
        """Hook for child classes during initialization."""
        pass

    # ---------------------------------------------------------
    # OPTIONAL EXTENSION HOOKS
    # ---------------------------------------------------------

    async def _check_start_preconditions(self) -> bool:
        """
        Asynchronous verification hook executed before the agent starts.
        By default, it should return True. Child classes can override this to check
        essential environment readiness or dependencies before starting.
        """
        return True, "Start precondition check successful"

    async def _check_preconditions(self, message: 'MessageEnvelope') -> tuple[bool,str]:
        """
        Asynchronous verification hook executed before a message is allowed to process.
        By default, it should return True. Child classes will override this to query
        database entries, check file-system matrices, or verify upstream dependencies.
        """
        return True, "Precondition check successful"

    async def _check_postconditions(self, message: 'MessageEnvelope', result: ProcessResult) -> tuple[bool,str]:
        """
        Asynchronous verification hook executed after process() completes successfully
        but before the final output state is committed or emitted.
        By default, it should return True.
        """
        return True, "Postcondition check successful"

    async def _on_shutdown(self) -> None:
        """Optional hook for child classes during shutdown."""
        pass

    # ---------------------------------------------------------
    # INSPECTION INTERFACES (URP Section 6)
    # ---------------------------------------------------------
    @property
    def state(self) -> Dict[str, Any]:
        """Returns a safe, read-only view of the agent's current state."""
        return {
            "agent_id": self.descriptor.agent_id,
            "status": self._state.status,
            "session_id": self._state.session_id,
            "mailbox_size": self.mailbox.qsize(),
            "last_process_result": self._state.last_process_result
        }