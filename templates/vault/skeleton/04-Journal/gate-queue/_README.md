# 04-Journal/gate-queue

Escalation queue, and ONLY escalations: facts about people's roles/identity,
contradictions with an `active` note (superseding is always a human decision), a write
destination the deterministic applier could not resolve, or any delete/merge request.
Everything else the daily pipeline judges is written straight to canon; nothing else
belongs in this folder.

Escalated items are stamped with an escalation timestamp and skipped by later automated
runs, they wait for the owner to decide. Once resolved, move or delete the item from
this folder (deleting a queue item, not a canon note, is fine).
