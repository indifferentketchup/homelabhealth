## MODIFIED Requirements

### Requirement: synthetic polling cap is enforced
The synthetic polling `useEffect` in `ModelsPanel` (lines 581-606) SHALL use a ref for `synthAttempts` so the interval reads the current attempt count.
**Reason**: Audit finding B11 -- `synthAttempts` read inside `setInterval` is always stale. The 60-attempt cap (`MAX_SYNTH_ATTEMPTS`) never actually stops polling, causing indefinite `testProvider` calls.
**Migration**: None -- polling behavior corrected.

#### Scenario: Polling stops at MAX_SYNTH_ATTEMPTS
- **WHEN** synthetic polling reaches `MAX_SYNTH_ATTEMPTS` for a row
- **THEN** `testProvider` is no longer called for that row in subsequent interval ticks

### Requirement: tier-logic is centralized
Tier classification knowledge SHALL be defined once in the `TIERS` array with `isCpu()`, `rationale(sysinfo)`, and `diskWarning()` methods.
**Reason**: Audit finding S7 -- tier classification duplicated in TIERS array (53-142), rationaleFor switch (157-187), isCpuTier check (1169), and GPU banner (1164-1178). Adding a new tier requires updating 5 separate locations.
**Migration**: None -- centralized lookup replaces scattered logic.

#### Scenario: Tier picker shows correct labels
- **WHEN** the SystemTab renders the tier picker
- **THEN** each tier's label, footprint, and detect string match the current TIERS array values exactly

#### Scenario: rationaleFor delegates to tier method
- **WHEN** `rationaleFor(sysinfo, recommended)` is called
- **THEN** it delegates to `TIERS.find(t => t.id === recommended)?.rationale(sysinfo)` and returns the same text as before

### Requirement: Playwright test IDs preserved
All Playwright test IDs in `SystemTab.jsx` SHALL remain unchanged.
**Reason**: Existing Playwright verify scripts depend on these selectors: `system-models-pull-all`, `system-model-pull-*`, `system-model-cancel-*`, `system-model-progress-*`, `system-synth-row-*`, `system-synth-test-*`, `system-synth-error-*`.

#### Scenario: Pull-all button test ID preserved
- **WHEN** the ModelsPanel renders with pending rows
- **THEN** the "Pull all" button has `data-testid="system-models-pull-all"`

#### Scenario: Per-row test IDs preserved
- **WHEN** the ModelsPanel renders model rows
- **THEN** each row has `data-testid="system-model-pull-{role}"`, `data-testid="system-model-cancel-{role}"`, and `data-testid="system-model-progress-{role}"` as applicable
