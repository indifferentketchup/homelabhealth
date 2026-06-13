## MODIFIED Requirements

### Requirement: memory_tools.py splits into three modules
The `memory_tools.py` module SHALL be split into `memory_tools.py` (tool definitions + registry), `memory_extraction.py` (extraction logic), and `memory_hooks.py` (hook registration + background extraction).
**Reason**: Audit finding S11 -- 4 distinct responsibilities in one module: tool definitions (30-240), background extraction (243-443), hook registration (446-509), convenience wrapper (512-550).
**Migration**: Re-export from memory_tools.py for backward compatibility.

#### Scenario: Existing imports from memory_tools still work
- **WHEN** code imports `manage_memory`, `search_memory`, `MEMORY_TOOLS`, `MEMORY_TOOL_FUNCTIONS` from `services.memory_tools`
- **THEN** the imports resolve without error

#### Scenario: New module imports work
- **WHEN** code imports `extract_from_exchange` from `services.memory_extraction`
- **THEN** the import resolves without error

#### Scenario: Hook registration works from new module
- **WHEN** code imports `register_memory_hooks` from `services.memory_hooks`
- **THEN** the import resolves without error and the hook is registered at startup

### Requirement: daily.append failure logged at warning level
The `_post_tool_memory_hook` function (line 487) SHALL log `engine.daily.append()` failures at `logger.warning` level.
**Reason**: Audit finding B5 -- audit trail errors are invisible in production logs at DEBUG level.
**Migration**: None -- log level change only.

#### Scenario: daily.append failure produces warning log
- **WHEN** `engine.daily.append()` throws an exception in `_post_tool_memory_hook`
- **THEN** a warning is logged with the exception details (not debug)
