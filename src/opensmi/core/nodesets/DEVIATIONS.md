# Deviations from the upstream nodesets

Changes in our copies of the NodeSet2 XML files that the nodeset owner has not (yet) adopted. Each one is proposed
upstream; remove its entry once an upstream release contains it.

## Opc.Ua.SmartFactory.MachineSet.NodeSet2.xml

Proposed upstream as `opensmi-issues skill-state-machine/02`.

| Node | Change |
|---|---|
| `HaltedToResetting` (i=5115) | added `HasCause` → `Reset` (i=7015) |
| `StartingToHalting` (i=5134) | added `HasCause` → `Halt` (i=7014) |
| `ResettingToHalting` (i=5125) | added `HasCause` → `Halt` (i=7014) |
| `SuspendingToHalting` (i=5144) | added `HasCause` → `Halt` (i=7014) |
| `CompletingToHalting` (i=5148) | added `HasCause` → `Halt` (i=7014) |
| i=5132 | browse and display name `RunningToSuspeneding` → `RunningToSuspending` |
