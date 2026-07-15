#!/usr/bin/env python3
"""Brain daemon -- persistent semantic search over the vault index.

Keeps the embedding model + index warm in RAM between calls (loading the
model cold takes 13-28s; a warm query costs under 100ms).

Endpoints (HTTP, localhost only):
  GET /health                  -> {status, instance_id, chunks, parents, model, built_at}
  GET /query?q=...             -> JSON results
      params: top_k (default 10), min_score (default 0.0),
              source, type, tag, chunk_type (filters),
              compact=1 (lean fields for context injection),
              mode=auto (tiered top-k by confidence: best>0.65->5, 0.50-0.65->3, else [])
  POST /reload                 -> force index reload

The index reloads automatically when manifest.json's mtime changes (e.g.
after embed.sh runs), without restarting the daemon or reloading the model.

Port, index location and instance_id all come from brain_config (never
hardcoded); managed as an OS service by the templates in templates/services/.
"""
import gc
import json
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import os

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_config  # noqa: E402

HOST = "127.0.0.1"

# Unloads the model from RAM after this many idle seconds (returns ~1.3-1.8GB to
# the OS); the next query reloads on demand (one-time 13-28s cost). 0 disables.
IDLE_TTL = float(os.environ.get("BRAIN_DAEMON_IDLE_TTL", "3600"))

_lock = threading.Lock()
_state = {
    "model": None, "embs": None, "embs_norm": None, "chunks": [],
    "manifest_meta": {}, "manifest_mtime": 0.0, "last_used": 0.0,
    "npz": None, "manifest": None,
}


def _load_index():
    import numpy as np
    npz = _state["npz"]
    manifest_path = _state["manifest"]
    manifest = json.loads(manifest_path.read_text())
    data = np.load(npz)
    embs = data["embeddings"]
    chunks = manifest["chunks"]
    if len(embs) != len(chunks):
        raise RuntimeError(
            f"inconsistent index (embeddings={len(embs)} != chunks={len(chunks)}); run embed.sh"
        )
    norms = (embs ** 2).sum(axis=1, keepdims=True) ** 0.5
    _state["embs"] = embs
    _state["embs_norm"] = embs / (norms + 1e-9)
    _state["chunks"] = chunks
    _state["manifest_meta"] = {k: v for k, v in manifest.items() if k != "chunks"}
    _state["manifest_mtime"] = manifest_path.stat().st_mtime
    print(f"[brain-daemon] index loaded: {len(chunks)} chunks", flush=True)


def _ensure_fresh():
    """Reloads the index if manifest.json changed on disk (post embed.sh)."""
    try:
        if _state["manifest"].stat().st_mtime != _state["manifest_mtime"]:
            print("[brain-daemon] manifest changed -- reloading index", flush=True)
            _load_index()
    except FileNotFoundError:
        pass


def _load_model():
    from sentence_transformers import SentenceTransformer
    name = _state["manifest_meta"].get("model", "paraphrase-multilingual-MiniLM-L12-v2")
    print(f"[brain-daemon] loading model {name}...", flush=True)
    _state["model"] = SentenceTransformer(name)
    # warm-up: first inference compiles kernels
    _state["model"].encode(["warmup"])
    print("[brain-daemon] model ready", flush=True)


def _ensure_model():
    """Loads the model on demand and marks last use (for idle-unload)."""
    if _state["model"] is None:
        _load_model()
    _state["last_used"] = time.monotonic()


def _idle_reaper():
    """Unloads the model after IDLE_TTL seconds without queries, returning RAM to the OS."""
    while True:
        time.sleep(60)
        with _lock:
            if _state["model"] is not None and \
                    (time.monotonic() - _state["last_used"]) > IDLE_TTL:
                print(f"[brain-daemon] idle > {IDLE_TTL:.0f}s -- unloading model", flush=True)
                _state["model"] = None
                gc.collect()
                try:
                    import torch
                    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                except Exception:  # noqa: BLE001 -- empty_cache is best-effort
                    pass


def do_query(q, top_k=10, min_score=0.0, source=None, type_=None, tag=None,
             chunk_type=None, compact=False, mode=None):
    import numpy as np
    with _lock:
        _ensure_fresh()
        _ensure_model()
        chunks = _state["chunks"]
        embs_n = _state["embs_norm"]
        model = _state["model"]

        keep = list(range(len(chunks)))
        if source:
            keep = [i for i in keep if str(chunks[i].get("source", "")).lower() == source.lower()]
        if type_:
            keep = [i for i in keep if str(chunks[i].get("type", "")).lower() == type_.lower()]
        if tag:
            t = tag.lower()
            keep = [i for i in keep
                    if any(t in str(x).lower() for x in (chunks[i].get("tags") or []))]
        if chunk_type:
            keep = [i for i in keep if chunks[i].get("chunk_type") == chunk_type]
        if not keep:
            return []

        q_emb = model.encode([q], convert_to_numpy=True)[0]
        q_emb = q_emb / ((q_emb ** 2).sum() ** 0.5 + 1e-9)
        sims = embs_n[keep] @ q_emb

        k = min(int(top_k), len(sims))
        order = np.argsort(-sims)[:k]
        results = [(float(sims[i]), chunks[keep[i]]) for i in order]

    results = [(s, c) for s, c in results if s >= float(min_score)]
    if mode == "auto" and results:
        # tiered top-k by confidence of the best hit
        best = results[0][0]
        if best > 0.65:
            results = results[:5]
        elif best >= 0.50:
            results = results[:3]
        else:
            results = []

    if compact:
        out = []
        for s, c in results:
            sec = c.get("section_title") or c.get("section_id") or ""
            st = str(c.get("status") or "")
            out.append({
                "score": round(s, 2),
                "path": c.get("parent_path"),
                "title": c.get("parent_title"),
                **({"section": sec[:120]} if sec else {}),
                "type": c.get("type"),
                "source": c.get("source"),
                # trust axis: only travels when the hit is NOT current truth
                **({"status": st} if st and st != "active" else {}),
            })
        return out
    return [{"score": s, **c} for s, c in results]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence access log (the service manager captures stdout)
        pass

    def _send(self, code, payload):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
        if parsed.path == "/health":
            self._send(200, {
                "status": "ok",
                "instance_id": _state.get("instance_id"),
                "chunks": len(_state["chunks"]),
                "parents": _state["manifest_meta"].get("parent_count"),
                "model": _state["manifest_meta"].get("model"),
                "model_loaded": _state["model"] is not None,
                "built_at": _state["manifest_meta"].get("built_at"),
            })
        elif parsed.path == "/query":
            q = params.get("q", "").strip()
            if not q:
                self._send(400, {"error": "param q is required"})
                return
            try:
                results = do_query(
                    q,
                    top_k=params.get("top_k", 10),
                    min_score=params.get("min_score", 0.0),
                    source=params.get("source"),
                    type_=params.get("type"),
                    tag=params.get("tag"),
                    chunk_type=params.get("chunk_type"),
                    compact=params.get("compact") == "1",
                    mode=params.get("mode"),
                )
                self._send(200, results)
            except Exception as e:  # noqa: BLE001 -- daemon must not die on a bad query
                self._send(500, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/reload":
            try:
                with _lock:
                    _load_index()
                self._send(200, {"status": "reloaded", "chunks": len(_state["chunks"])})
            except Exception as e:  # noqa: BLE001
                self._send(500, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})


def main():
    index_dir = brain_config.index_dir()
    _state["npz"] = index_dir / "embeddings.npz"
    _state["manifest"] = index_dir / "manifest.json"
    _state["instance_id"] = brain_config.instance_id()
    port = brain_config.port()

    # First install: the index may not exist yet (embed runs after the service
    # starts under keep-alive). Wait politely instead of crash-looping.
    import time as _time
    while True:
        try:
            _load_index()
            break
        except FileNotFoundError:
            print("[brain-daemon] index not built yet; retrying in 30s", flush=True)
            _time.sleep(30)
    if IDLE_TTL > 0:
        # Model loads on demand on the first query; the reaper unloads it when idle.
        threading.Thread(target=_idle_reaper, daemon=True).start()
        print(f"[brain-daemon] idle-unload active (TTL={IDLE_TTL:.0f}s)", flush=True)
    else:
        _load_model()
    server = ThreadingHTTPServer((HOST, port), Handler)
    print(f"[brain-daemon] instance_id={_state['instance_id']} serving on http://{HOST}:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
    except brain_config.ConfigError as e:
        print(f"[brain-daemon] ConfigError: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
