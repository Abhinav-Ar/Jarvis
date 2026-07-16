# ORION architecture

ORION is maintained as a modular monolith: one deployable macOS product with clear
ownership boundaries and durable adapters. This keeps local workflows fast while
allowing individual workers to evolve independently.

## Source ownership

- `src/orion/` owns the Python runtime, orchestration, workers, integrations, and
  local persistence. Runtime modules live together so the background deployment
  is atomic and imports cannot accidentally resolve against development-only files.
- `src/orion/personal_intelligence.py` owns the private personal timeline,
  relationship aliases, connector health, and local-first recall.
- `packaging/macos/` owns the Swift menu controller, HUD, desktop helper, launchd
  definitions, and bundle metadata.
- `scripts/` owns setup, development launch, deployment, removal, and validation.
- `tests/` mirrors runtime capabilities with unit and regression coverage.
- `docs/` owns architecture, operating procedures, and contributor decisions.

## Runtime boundaries

1. `jarvis.py` is the interactive process entrypoint.
2. `assist.py` owns conversation orchestration and delegates durable planning to
   `task_engine.py`.
3. `tools.py` is the capability boundary. It exposes bounded schemas and dispatches
   into integrations or native workers.
4. `execution_supervisor.py` provides observe, checkpoint, act, verify, recovery,
   and cancellation contracts for every consequential action.
5. Native workers create inspectable artifacts inside `~/Documents/ORION Projects`.
6. `agent_platform.py` and `orion_kernel.py` own durable local state and never store
   API secrets in task history or replay records.

## Dependency direction

Entrypoints may depend on orchestration; orchestration may depend on capabilities;
capabilities may depend on integrations and workers. Workers may depend on shared
workspace, diagnostics, and supervision modules. Integrations and workers must not
import the interactive entrypoint.

Engineering and creative workers are specialist leaves behind the central personal
intelligence and conversation layers; they are not the default routing destination.

## Compatibility

The root launchers remain intentionally small so existing commands continue to
work. Production code belongs under `src/orion`; new implementation modules should
not be added to the repository root.
