## MODIFIED Requirements

### Requirement: send() SSE path handles synchronous throws
The `send()` function's SSE existing-chat path (lines 514-518) SHALL wrap `await runStream(...)` in a try/catch that resets UI state on failure.
**Reason**: Audit finding B7 -- if `runStream` throws synchronously before `consumeStream` starts, `pendingSend` is stuck at `true` and the UI enters permanent busy state requiring page refresh.
**Migration**: None -- error handling only.

#### Scenario: Synchronous throw in send() resets UI
- **WHEN** `runStream()` throws synchronously in the SSE existing-chat path
- **THEN** `pendingSend` is set to `false`, `streamText` is cleared, `optimisticUser` is cleared, `clearStreamUi()` is called, and `sendError` is set

### Requirement: retryLastSend() handles synchronous throws
The `retryLastSend()` function (lines 569-576) SHALL wrap `void runStream(...)` in a try/catch that resets UI state on failure.
**Reason**: Audit finding B13 -- same stuck-state risk as B7.
**Migration**: None -- error handling only.

#### Scenario: Synchronous throw in retry resets UI
- **WHEN** `runStream()` throws synchronously in the retry path
- **THEN** `pendingSend` is set to `false`, `streamText` is cleared, `clearStreamUi()` is called, and `sendError` is set

### Requirement: durable sync effect uses ref for chat ID
The durable sync effect (lines 265-296) SHALL use a ref to store the initiating chat ID instead of reading `activeChatId` from the closure.
**Reason**: Audit finding B8 -- when switching chats while a durable stream completes, `listMessages(cid)` may fetch the wrong chat's messages.
**Migration**: None -- internal state management only.

#### Scenario: Chat switch during durable stream fetches correct messages
- **WHEN** the user switches chats while a durable stream is completing
- **THEN** `listMessages` is called with the chat ID that initiated the stream, not the newly active chat

### Requirement: forkAndStream clears stream UI on error
The `forkAndStream()` catch block (lines 538-544) SHALL call `clearStreamUi()` after resetting other state.
**Reason**: Audit finding B15 -- after failure, stale phase indicators remain visible.
**Migration**: None -- UI cleanup only.

#### Scenario: forkAndStream error clears phase indicators
- **WHEN** `forkAndStream()` throws an error
- **THEN** `clearStreamUi()` is called, removing stale phase indicators from the UI

### Requirement: send() extracts createChatIfNeeded helper
The `send()` function SHALL use a `createChatIfNeeded()` helper for the "create chat if no active chat" block duplicated at lines 428-455 (durable) and 475-511 (SSE).
**Reason**: Audit finding S15 -- 4 code paths with ~60 lines of duplicated state management.
**Migration**: None -- behavior-preserving refactor.

#### Scenario: Durable path creates chat when none active
- **WHEN** `send()` is called with `durableEnabled=true` and no `activeChatId`
- **THEN** a new chat is created via `createChat()`, state is hydrated, and `durable.sendMessage` is called

#### Scenario: SSE path creates chat when none active
- **WHEN** `send()` is called with `durableEnabled=false` and no `activeChatId`
- **THEN** a new chat is created via `createChat()`, state is hydrated, and `runStream` is called

### Requirement: runStream uses named callback builders
The `runStream()` function SHALL use named callback builders (`makeOnToken`, `makeOnSearchSources`, etc.) instead of inline anonymous functions.
**Reason**: Audit finding S16 -- 8 anonymous callback functions, none independently testable.
**Migration**: None -- behavior-preserving refactor.

#### Scenario: Stream tokens update state via named callback
- **WHEN** tokens arrive during streaming
- **THEN** `onToken` callback (built by `makeOnToken`) updates `streamPhase` and `streamText` identically to the current inline version
