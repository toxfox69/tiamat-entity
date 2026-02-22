"""
Shared opportunity queue between background scanners and TIAMAT's main loop.
Background processes WRITE opportunities. TIAMAT's cycle loop READS and ACTS on them.
Uses file locking so multiple processes don't corrupt it.
"""
import json
import time
import fcntl

QUEUE_FILE = "/root/.automaton/opportunity_queue.json"


class OpportunityQueue:

    @staticmethod
    def push(opportunity):
        """Add an opportunity to the queue (called by scanner/sniper)."""
        with open(QUEUE_FILE, "a+") as f:
            fcntl.flock(f, fcntl.LOCK_EX)
            f.seek(0)
            try:
                queue = json.load(f)
            except (json.JSONDecodeError, ValueError):
                queue = []

            opportunity["queued_at"] = time.time()
            opportunity["status"] = "pending"
            queue.append(opportunity)

            # Keep max 50 items
            if len(queue) > 50:
                queue = queue[-50:]

            f.seek(0)
            f.truncate()
            json.dump(queue, f, indent=2, default=str)
            fcntl.flock(f, fcntl.LOCK_UN)

    @staticmethod
    def peek():
        """Read all pending opportunities (called by TIAMAT)."""
        try:
            with open(QUEUE_FILE) as f:
                fcntl.flock(f, fcntl.LOCK_SH)
                queue = json.load(f)
                fcntl.flock(f, fcntl.LOCK_UN)
            return [o for o in queue if o.get("status") == "pending"]
        except (FileNotFoundError, json.JSONDecodeError, ValueError):
            return []

    @staticmethod
    def mark_done(index, result="acted"):
        """Mark opportunity as handled (called by TIAMAT after acting)."""
        try:
            with open(QUEUE_FILE, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                queue = json.load(f)
                if 0 <= index < len(queue):
                    queue[index]["status"] = result
                    queue[index]["acted_at"] = time.time()
                f.seek(0)
                f.truncate()
                json.dump(queue, f, indent=2, default=str)
                fcntl.flock(f, fcntl.LOCK_UN)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    @staticmethod
    def mark_done_by_address(address, result="acted"):
        """Mark opportunity done by contract address."""
        try:
            with open(QUEUE_FILE, "r+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                queue = json.load(f)
                for o in queue:
                    if o.get("address") == address and o.get("status") == "pending":
                        o["status"] = result
                        o["acted_at"] = time.time()
                f.seek(0)
                f.truncate()
                json.dump(queue, f, indent=2, default=str)
                fcntl.flock(f, fcntl.LOCK_UN)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
