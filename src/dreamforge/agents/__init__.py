"""Layer B: LangGraph-orchestrated agents over the deterministic core.

The agents are READ-ONLY observers of emitted event streams; any state
change goes through typed commands that the engine's gate validates and may
refuse (MASTER_PROMPT.md §6.1). The deterministic core never imports this
package.
"""
