"""
Auto-Optimization Engine — Multi-Armed Bandit (Thompson Sampling).

Periodically reads the events audit log, traces rewards back to split nodes
via leads.path_history, and updates the Beta distribution params stored in
sequence_nodes.data.weights.

Reward schedule (higher = stronger signal):
  event_type='invite_accepted'  → +1
  event_type='email_sent'       → +1  (engagement proxy)
  event_type='reply_received'   → +5
  event_type='dm_sent'          → +1
"""
import json
import logging

from app.db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

# Minimum leads per arm before weights shift away from 50/50
MIN_SAMPLES = 10

REWARD_WEIGHTS = {
    "invite_accepted": 1,
    "email_sent": 1,
    "dm_sent": 1,
    "reply_received": 5,
}


async def run_optimization() -> None:
    """Entry point called by the cron worker."""
    split_nodes = await fetch_all(
        """
        SELECT sn.id, sn.campaign_id, sn.data
        FROM sequence_nodes sn
        JOIN campaigns c ON c.id = sn.campaign_id
        WHERE sn.node_type = 'split' AND c.status = 'active'
        """
    )
    if not split_nodes:
        return

    log.info(f"[optimization] Running bandit update for {len(split_nodes)} split nodes")
    for node in split_nodes:
        await _update_node_weights(node)


async def _update_node_weights(node: dict) -> None:
    node_id = str(node["id"])

    # Find all leads that passed through this split node
    leads = await fetch_all(
        "SELECT id FROM leads WHERE path_history @> $1::jsonb",
        json.dumps([{"split_node_id": node_id}]),
    )
    if not leads:
        return

    arm_stats: dict[str, dict[str, float]] = {
        "true": {"total": 0, "reward": 0.0},
        "false": {"total": 0, "reward": 0.0},
    }

    for lead_row in leads:
        lead_id = str(lead_row["id"])
        lead = await fetch_one(
            "SELECT path_history FROM leads WHERE id=$1", lead_id
        )
        if not lead:
            continue

        history = lead.get("path_history") or []
        arm = _find_arm_for_split(history, node_id)
        if arm not in arm_stats:
            continue

        arm_stats[arm]["total"] += 1

        # Sum reward signals for this lead
        events = await fetch_all(
            "SELECT event_type FROM events WHERE lead_id=$1", lead_id
        )
        reward = sum(REWARD_WEIGHTS.get(e["event_type"], 0) for e in events)
        arm_stats[arm]["reward"] += reward

    # Only update if we have enough samples per arm to be meaningful
    for arm_data in arm_stats.values():
        if arm_data["total"] < MIN_SAMPLES:
            log.debug(
                f"[optimization] Node {node_id}: insufficient samples, skipping"
            )
            return

    # Build new Beta params: alpha = reward_sum + 1, beta = (total - wins) + 1
    # "win" = at least 1 reward point
    new_weights: dict[str, dict[str, float]] = {}
    for arm, stats in arm_stats.items():
        wins = stats["reward"]
        losses = max(0, stats["total"] - wins)
        new_weights[arm] = {
            "alpha": round(wins + 1, 2),
            "beta": round(losses + 1, 2),
        }

    data = dict(node["data"] or {})
    data["weights"] = new_weights

    await execute(
        "UPDATE sequence_nodes SET data=$1 WHERE id=$2",
        json.dumps(data),
        node["id"],
    )
    log.info(
        f"[optimization] Node {node_id} weights updated: "
        f"A(α={new_weights['true']['alpha']}, β={new_weights['true']['beta']}) | "
        f"B(α={new_weights['false']['alpha']}, β={new_weights['false']['beta']})"
    )


def _find_arm_for_split(path_history: list, split_node_id: str) -> str | None:
    for entry in path_history:
        if isinstance(entry, dict) and str(entry.get("split_node_id")) == split_node_id:
            return entry.get("arm")
    return None
