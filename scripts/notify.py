#!/usr/bin/env python3
"""notify: the brain's single notification channel (ntfy.sh).

The topic is ALWAYS read from config.ntfy_topic_file (single source; changing
the topic means editing that one file). There is no hardcoded fallback topic:
if the file is missing or empty, the send fails loudly to stderr instead of
silently posting to a made-up channel.

As a module:  from notify import send
  send("message")                                    # default info
  send("something broke", title="brain watchdog", priority="high", tags="warning")
As a CLI:     notify.py "message" [--title T] [--priority high] [--tags warning]
"""
import sys
import argparse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def send(msg, title=None, priority=None, tags=None, timeout=10):
    """Send a notification; never raises (a notification must not take a job down)."""
    try:
        # Config access stays INSIDE the try: a corrupted/missing config at
        # notification time must not crash a job whose real work already finished.
        import brain_config
        topic = brain_config.ntfy_topic()
        if not topic:
            print("[notify] no ntfy topic configured (config.ntfy_topic_file missing or "
                  "empty); notification dropped", file=sys.stderr)
            return False
        req = urllib.request.Request(f"https://ntfy.sh/{topic}",
                                     data=msg.encode("utf-8"), method="POST")
        if title:
            req.add_header("Title", title.encode("utf-8").decode("latin-1", "replace"))
        if priority:
            req.add_header("Priority", priority)
        if tags:
            req.add_header("Tags", tags)
        urllib.request.urlopen(req, timeout=timeout)
        return True
    except Exception as e:
        print(f"[notify] failed (non-critical): {e}", file=sys.stderr)
        return False


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("msg")
    ap.add_argument("--title")
    ap.add_argument("--priority")
    ap.add_argument("--tags")
    a = ap.parse_args()
    ok = send(a.msg, title=a.title, priority=a.priority, tags=a.tags)
    sys.exit(0 if ok else 1)
