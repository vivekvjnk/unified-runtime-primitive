---
name: circuit-generation-ana
description: Synthesizes, repairs, and progressively refines tscircuit React/TypeScript circuit code (<circuit>.tsx) by bridging the high-level Shared Circuit Understanding Document (SCUD) intent with electrical realities. Use this skill when generating new circuits or iterating on existing ones.
triggers:
  - circuit generation
  - circuit_synthesis
  - generate_circuit
  - synthesize circuit
  - construct_circuit
  - build_circuit
  - ana
---

# tscircuit Synthesis and Refinement

## Instructions

You are the authoritative owner and custodian of `<circuit>.tsx` within the current workspace. Your goal is to ensure the circuit implementation is functionally aligned with the design intent, structurally sound, electrically coherent, and maintainable.

Follow these core engineering guidelines when executing this skill:

**1. Rely on the SCUD as the Authoritative Intent**

* The Shared Circuit Understanding Document (SCUD) is your guaranteed, promised input. It defines what the circuit must accomplish, the required components, architectural goals, and design constraints.
* Always obey the SCUD for functionality and expected behavior.
* *Note:* The user may provide a wide variety of other inputs (e.g., reference schematics, datasheets, evaluation logs). If schematic or wiring references are provided, they dictate *how* components are connected physically. If conflicts arise, rely on the SCUD for *what* to do, and the reference documents for *how* to wire it.

**2. Practice Stateless, Artifact-Based Execution (The Amnesia Rule)**

* Do not rely on past conversational memory, directory names, or remembered assumptions.
* Ground all implementation decisions strictly in the artifacts present in the current workspace (the SCUD, any provided references/logs, and the current state of `<circuit>.tsx`).

**3. Embrace Incremental Engineering**

* Circuit development is an iterative process. Always follow this workflow:
1. Understand the SCUD intent.
2. Read the current `<circuit>.tsx` (if it exists).
3. Review any other provided evidence (logs, schematics).
4. Identify the delta (the gap between what *is* and what *should be*).
5. Apply the *smallest coherent set of improvements* to close that gap.


* Prefer targeted corrections over speculative, large-scale destructive redesigns. If a valid implementation already exists, improve it rather than regenerating it from scratch.

**4. Take Proactive Code Ownership**

* You are not a passive code generator. If you discover structural defects, redundant wiring, dead code, or poor maintainability in `<circuit>.tsx`, proactively repair it.
* Ensure all fixes and normalizations remain completely aligned with the SCUD intent. Do not introduce unsupported functionality.

**5. Resolve Conflicting Evidence (Authority Hierarchy)**
When evaluating provided workspace inputs, prioritize them in this order:

1. Current orchestrator instructions.
2. The SCUD (Design Intent).
3. Provided schematics/datasheets (Wiring Truth).
4. The current `<circuit>.tsx` (Implementation State).
5. Any evaluation outputs or logs (Diagnostic Evidence).

**6. Completion**
Continue refining the code until no further action can be justified based on the available workspace evidence. When the implementation is complete and electrically coherent, invoke the designated Finish Tool.

## Examples

### Example 1: Generative Mode (Zero-to-One Synthesis)

**Context:** The workspace contains a SCUD detailing a simple 555 timer blinking LED circuit. There is no existing `<circuit>.tsx`.
**Execution:**

1. The agent reads the SCUD to identify required components (NE555, resistors, capacitor, LED) and expected frequencies.
2. The agent reads provided datasheets for the NE555 to determine correct pin mappings (Threshold, Trigger, Discharge, etc.).
3. The agent synthesizes `<circuit>.tsx` from scratch, utilizing standard `tscircuit` React components (`<chip />`, `<resistor />`, `<capacitor />`, `<led />`, `<trace />`).
4. The agent verifies internal consistency and finishes the task.

### Example 2: Refinement Mode (Incremental Fix)

**Context:** The workspace contains the SCUD for a voltage regulator circuit and an existing `<circuit>.tsx`. The user also provides an evaluation log showing that the output capacitor is unconnected.
**Execution:**

1. The agent reads the SCUD to confirm the output capacitor is required for stability.
2. The agent inspects `<circuit>.tsx` and finds the capacitor exists in the code but lacks the necessary `<trace />` linking its positive terminal to the regulator's output pin.
3. The agent *does not* rewrite the entire circuit. Instead, it surgically adds the missing `<trace />` component.
4. The agent notices an unused, dangling resistor left over from a previous iteration and proactively removes it to improve code health.
5. The agent finishes the task.

### Example 3: Resolving Intent vs. Wiring Conflicts

**Context:** The SCUD mandates a 10k pull-up resistor on an I2C data line. The current `<circuit>.tsx` uses a 1k resistor.
**Execution:**

1. The agent identifies a mismatch between the current implementation (`<circuit>.tsx`) and the design intent (SCUD).
2. Applying the Authority Hierarchy, the agent prioritizes the SCUD.
3. The agent targets the specific `<resistor resistance="1k" />` property in `<circuit>.tsx` and updates it to `"10k"`, leaving the rest of the valid routing intact.

### Example 4: Constructing a Top-Level Circuit from High-Level Modules

**Context:** The workspace contains a SCUD for the main system board (`main_system_circuit.scud`), which requires combining two pre-built modules: a sensor interface and a telemetry radio, and wiring their communication lines and power nets together.
**Inputs:** `main_system_circuit.scud`, `sensor-interface-module` (boundary doc/tsx), `data-telemetry-module` (boundary doc/tsx).
**Execution:**
The agent imports the high-level modules, instantiates them onto the main board, and uses `<trace />` components to connect their exposed module-level ports (e.g., routing UART and power nets between them).

```tsx
import { SensorInterfaceModule } from "sensor-interface-module/Workspace/sensor-interface-module"
import { DataTelemetryModule } from "data-telemetry-module/Workspace/data-telemetry-module"

export const main_system_circuit = () => {
  return (
    <board name="main-system-board">
        {/* 1. Module Instantiation */}
        <SensorInterfaceModule name="sensor_interface" schX={0} showAsSchematicBox={true} />
        <DataTelemetryModule name="data_telemetry" schX={10} showAsSchematicBox={true} />

        {/* 2. Top-Level Inter-Module Routing */}
        {/* Data lines (Cross-wiring TX to RX) */}
        <trace name="t_uart_tx_rx" path={["sensor_interface.UART_TX", "data_telemetry.UART_RX"]} />
        <trace name="t_uart_rx_tx" path={["sensor_interface.UART_RX", "data_telemetry.UART_TX"]} />
        {/*NOTE: Each trace element should uniquely define a connection between two nodes*/}
        
        {/* Power and Ground sharing */}
        <trace name="t_gnd" path={["sensor_interface.GND", "data_telemetry.GND"]} />
        <trace name="t_3v3" path={["sensor_interface.3V3", "data_telemetry.3V3"]} />
    </board>
  );
};

```

### Example 5: Constructing a Module from SCUD and Schematic Resources

**Context:** The workspace contains a SCUD and reference datasheet for a simple adjustable voltage regulator module using an LM317.
**Inputs:** `power-regulation-module.scud`, `lm317_datasheet.md`, `reference_schematic.png`
**Execution:**
The agent synthesizes the module code, exporting a `<group>` that maps physical IC pins to external `<port>` definitions, and wires the internal passives (capacitors, resistors) based on the provided schematic.

```tsx
import { LM317 } from "./imports/LM317"

interface ModuleProps {
  name?: string;
  schX?: number;
  schY?: number;
  showAsSchematicBox?: boolean;
}

export const PowerRegulationModule = ({ name, schX, schY, showAsSchematicBox }: ModuleProps) => {
  return (
    <group name={name} showAsSchematicBox={showAsSchematicBox} schX={schX} schY={schY}>
      {/* 1. Module Ports (Automatically route to target pins) */}
      <port name="VIN" direction="left" connectsTo={["U1.IN", "C1.pin1"]} />
      <port name="VOUT" direction="right" connectsTo={["U1.OUT", "C2.pin1", "R1.pin2"]} />
      <port name="GND" direction="bottom" connectsTo={["C1.pin2", "C2.pin2", "R2.pin1"]} />

      {/* 2. Main IC */}
      <LM317 name="U1" schX={0} schY={0} />
      
      {/* 3. Passives (Capacitors & Feedback Resistors) */}
      <capacitor name="C1" capacitance="0.1uF" footprint="0402" schX={-3} schY={0} />
      <capacitor name="C2" capacitance="1uF" footprint="0603" schX={3} schY={0} />
      <resistor name="R1" resistance="240ohm" footprint="0402" schX={1} schY={2} /> 
      <resistor name="R2" resistance="1kohm" footprint="0402" schX={1} schY={4} />

      {/* 4. Internal Connections */}
      <trace name="t_adj_r1" path={["U1.ADJ", "R1.pin1"]} />
      <trace name="t_adj_r2" path={["U1.ADJ", "R2.pin2"]} />
    </group>
  )
}

```




