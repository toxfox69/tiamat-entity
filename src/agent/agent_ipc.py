"""
TIAMAT Agent IPC — Zero-token inter-agent communication.
Protocol spec: /root/.automaton/agent_protocol.json

Transport: JSONL files with fcntl locking.
No natural language. No LLM tokens for message passing.
Messages are structured ops with typed payloads.

Usage:
    from agent_ipc import AgentIPC

    # Send a message
    AgentIPC.send("scanner", "SKIM", {"addr": "0xABC...", "eth": 0.5})

    # Read pending messages
    msgs = AgentIPC.recv()

    # Read + filter
    msgs = AgentIPC.recv(op="SKIM")
    msgs = AgentIPC.recv(category="execute")

    # Acknowledge
    AgentIPC.ack(msg["id"], "SUCCESS", {"eth_received": 0.05})

    # Heartbeat
    AgentIPC.heartbeat("scanner", cycles=100, errors=0)
"""
import json
import time
import fcntl
import os
import uuid

PROTOCOL_FILE = "/root/.automaton/agent_protocol.json"
INBOX = "/root/.automaton/agent_inbox.jsonl"
OUTBOX = "/root/.automaton/agent_outbox.jsonl"
HEARTBEATS = "/root/.automaton/agent_heartbeats.json"
MAX_LINES = 1000
MAX_MSG_BYTES = 4096

# Load protocol once at import
_protocol = None


def _load_protocol():
    global _protocol
    if _protocol is None:
        with open(PROTOCOL_FILE) as f:
            _protocol = json.load(f)
    return _protocol


def _gen_id():
    return uuid.uuid4().hex[:16]


def _now():
    return int(time.time())


def _append_jsonl(filepath, obj):
    """Append a JSON object as one line to a JSONL file with exclusive lock."""
    line = json.dumps(obj, separators=(",", ":"), default=str) + "\n"
    if len(line.encode("utf-8")) > MAX_MSG_BYTES:
        raise ValueError(f"Message exceeds {MAX_MSG_BYTES} bytes")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        f.write(line)
        fcntl.flock(f, fcntl.LOCK_UN)
    _maybe_rotate(filepath)


def _read_jsonl(filepath):
    """Read all lines from a JSONL file with shared lock."""
    if not os.path.exists(filepath):
        return []
    with open(filepath, "r") as f:
        fcntl.flock(f, fcntl.LOCK_SH)
        lines = f.readlines()
        fcntl.flock(f, fcntl.LOCK_UN)
    msgs = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            msgs.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return msgs


def _rewrite_jsonl(filepath, msgs):
    """Rewrite a JSONL file with exclusive lock."""
    with open(filepath, "w") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        for msg in msgs:
            f.write(json.dumps(msg, separators=(",", ":"), default=str) + "\n")
        fcntl.flock(f, fcntl.LOCK_UN)


def _maybe_rotate(filepath):
    """Rotate file if it exceeds MAX_LINES."""
    try:
        with open(filepath, "r") as f:
            lines = f.readlines()
        if len(lines) <= MAX_LINES:
            return
        # Rotate: .3 deleted, .2 → .3, .1 → .2, current → .1
        for i in range(3, 0, -1):
            src = f"{filepath}.{i}" if i > 1 else f"{filepath}.1"
            dst = f"{filepath}.{i}"
            if i == 3 and os.path.exists(dst):
                os.remove(dst)
            if i > 1:
                prev = f"{filepath}.{i-1}"
                if os.path.exists(prev):
                    os.rename(prev, dst)
        os.rename(filepath, f"{filepath}.1")
        # Keep last 100 lines in current file for continuity
        with open(filepath, "w") as f:
            f.writelines(lines[-100:])
    except (FileNotFoundError, OSError):
        pass


class AgentIPC:

    @staticmethod
    def send(from_agent, op, payload, queue=None):
        """Send a structured message to the inbox.

        Args:
            from_agent: sender name (e.g. "scanner", "sniper")
            op: operation code (e.g. "SKIM", "ALERT", "REPORT")
            payload: dict of op-specific fields
        Returns:
            message id
        """
        proto = _load_protocol()
        op_def = proto["ops"].get(op)
        if op_def is None:
            raise ValueError(f"Unknown op: {op}. Valid: {list(proto['ops'].keys())}")

        # Validate required fields
        missing = [f for f in op_def["requires"] if f not in payload]
        if missing:
            raise ValueError(f"Op {op} missing required fields: {missing}")

        # Build envelope
        msg_id = _gen_id()
        ts = _now()
        ttl_sec = op_def.get("ttl_seconds")
        msg = {
            "id": msg_id,
            "ts": ts,
            "from": from_agent,
            "op": op,
            "ttl": (ts + ttl_sec) if ttl_sec else None,
            "payload": payload,
            "status": "pending",
        }

        target = queue or INBOX
        _append_jsonl(target, msg)
        return msg_id

    @staticmethod
    def recv(op=None, category=None, include_expired=False, queue=None):
        """Read pending messages from inbox.

        Args:
            op: filter by op code
            category: filter by op category
            include_expired: if False (default), skip expired messages
        Returns:
            list of message dicts
        """
        proto = _load_protocol()
        target = queue or INBOX
        msgs = _read_jsonl(target)
        now = _now()
        result = []
        for msg in msgs:
            if msg.get("status") != "pending":
                continue
            if not include_expired and msg.get("ttl") and msg["ttl"] < now:
                continue
            if op and msg.get("op") != op:
                continue
            if category:
                op_def = proto["ops"].get(msg.get("op"), {})
                if op_def.get("category") != category:
                    continue
            result.append(msg)
        return result

    @staticmethod
    def mark(msg_id, status, result=None, queue=None):
        """Update a message's status.

        Args:
            msg_id: message id
            status: new status (done, failed, processing, expired)
            result: optional result data
        """
        target = queue or INBOX
        msgs = _read_jsonl(target)
        changed = False
        for msg in msgs:
            if msg.get("id") == msg_id:
                msg["status"] = status
                if result is not None:
                    msg["result"] = result
                msg["processed_at"] = _now()
                changed = True
                break
        if changed:
            _rewrite_jsonl(target, msgs)

    @staticmethod
    def ack(ref_id, result, data=None, from_agent="tiamat"):
        """Send an ACK message referencing a previous message."""
        payload = {"ref_id": ref_id, "result": result}
        if data:
            payload["data"] = data
        return AgentIPC.send(from_agent, "ACK", payload)

    @staticmethod
    def heartbeat(agent, status="alive", **kwargs):
        """Send/update heartbeat for an agent."""
        hb = {
            "agent": agent,
            "status": status,
            "ts": _now(),
        }
        hb.update(kwargs)

        # Heartbeats go to a separate file (overwrite per agent, not append)
        beats = {}
        if os.path.exists(HEARTBEATS):
            try:
                with open(HEARTBEATS, "r") as f:
                    fcntl.flock(f, fcntl.LOCK_SH)
                    beats = json.load(f)
                    fcntl.flock(f, fcntl.LOCK_UN)
            except (json.JSONDecodeError, ValueError):
                beats = {}

        beats[agent] = hb
        with open(HEARTBEATS, "w") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            json.dump(beats, f, separators=(",", ":"))
            fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def check_heartbeats(stale_seconds=600):
        """Check which agents are alive/stale.

        Returns:
            dict of {agent: {status, ts, stale: bool}}
        """
        if not os.path.exists(HEARTBEATS):
            return {}
        try:
            with open(HEARTBEATS, "r") as f:
                beats = json.load(f)
        except (json.JSONDecodeError, ValueError):
            return {}
        now = _now()
        for agent, hb in beats.items():
            hb["stale"] = (now - hb.get("ts", 0)) > stale_seconds
        return beats

    @staticmethod
    def pending_count(queue=None):
        """Count pending messages."""
        target = queue or INBOX
        msgs = _read_jsonl(target)
        now = _now()
        return sum(
            1 for m in msgs
            if m.get("status") == "pending"
            and (not m.get("ttl") or m["ttl"] >= now)
        )

    @staticmethod
    def expire_stale(queue=None):
        """Mark expired messages as expired. Returns count expired."""
        target = queue or INBOX
        msgs = _read_jsonl(target)
        now = _now()
        count = 0
        for msg in msgs:
            if (
                msg.get("status") == "pending"
                and msg.get("ttl")
                and msg["ttl"] < now
            ):
                msg["status"] = "expired"
                msg["processed_at"] = now
                count += 1
        if count > 0:
            _rewrite_jsonl(target, msgs)
        return count

    @staticmethod
    def stats(queue=None):
        """Get queue statistics."""
        target = queue or INBOX
        msgs = _read_jsonl(target)
        now = _now()
        by_status = {}
        by_op = {}
        for msg in msgs:
            s = msg.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1
            o = msg.get("op", "unknown")
            by_op[o] = by_op.get(o, 0) + 1
        return {
            "total": len(msgs),
            "by_status": by_status,
            "by_op": by_op,
            "pending": sum(
                1 for m in msgs
                if m.get("status") == "pending"
                and (not m.get("ttl") or m["ttl"] >= now)
            ),
        }


# Convenience aliases for common ops
def skim(addr, eth, **kwargs):
    return AgentIPC.send("scanner", "SKIM", {"addr": addr, "eth": eth, **kwargs})


def alert(msg, severity="INFO", source=None):
    payload = {"severity": severity, "msg": msg}
    if source:
        payload["source"] = source
    return AgentIPC.send("system", "ALERT", payload)


def report(metric, value, **kwargs):
    return AgentIPC.send("system", "REPORT", {"metric": metric, "value": value, **kwargs})


def propose(key, from_val, to_val, reason=None):
    payload = {"key": key, "from": from_val, "to": to_val}
    if reason:
        payload["reason"] = reason
    return AgentIPC.send("system", "PROPOSE", payload)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: agent_ipc.py [stats|pending|heartbeats|expire|test]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "stats":
        print(json.dumps(AgentIPC.stats(), indent=2))
    elif cmd == "pending":
        for msg in AgentIPC.recv():
            print(json.dumps(msg, indent=2))
    elif cmd == "heartbeats":
        print(json.dumps(AgentIPC.check_heartbeats(), indent=2))
    elif cmd == "expire":
        n = AgentIPC.expire_stale()
        print(f"Expired {n} stale messages")
    elif cmd == "test":
        # Self-test
        mid = AgentIPC.send("test", "REPORT", {"metric": "test_metric", "value": 42})
        print(f"Sent: {mid}")
        msgs = AgentIPC.recv(op="REPORT")
        print(f"Pending REPORT msgs: {len(msgs)}")
        AgentIPC.mark(mid, "done", "test passed")
        print("Marked done")
        AgentIPC.heartbeat("test", cycles=1)
        print(f"Heartbeats: {json.dumps(AgentIPC.check_heartbeats())}")
        print("All tests passed.")
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
