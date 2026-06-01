"""Execution plane: the workers that drive a lead through the canvas DAG.

  dispatcher.py        — node intent (on omni.events) -> ActionCommand on
                         outreach.commands (the Rust muscle consumes it)
  transition_worker.py — outreach.transitions (from the Flink orchestrator)
                         -> walk the canvas edge -> advance lead -> next node

Shared command-construction (node type -> channel, payload, credential ref)
lives in commands.py.
"""
