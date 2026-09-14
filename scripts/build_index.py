"""Build the semantic recall index.

candidates() in agent/engine/scan.py rejects a real match: purchase
amz-2019-0714 ("LED projecting finger lights party favors 50 pieces
multicolor") against CPSC recall 26761 ("Cade California Electronic
Projecting Finger Light Toys"), because the two strings share almost no
tokens and the lexical floor is 18%. The receipt and the notice are two
different people describing the same box of blinking party favors, and a
token-overlap filter has no way to know that "projecting finger lights" and
"Projecting Finger Light Toys" are the same four words in a different order
plus a plural.

This script embeds every recall notice from the three captured feeds
(data/cpsc_2026.json, data/openfda_sample.json, data/nhtsa_sample.json) with
BAAI/bge-small-en-v1.5, a 384-dim open sentence embedding model, and writes
the vectors to data/index/recalls.npz plus a JSON sidecar naming which
recall each row belongs to. agent/engine/retrieval.py loads that artifact
with no GPU and no network; only this build step needs the model, and only
once.

bge-small-en-v1.5 is an asymmetric retrieval model: passages (the recall
notices, embedded here) are encoded as-is, and queries (a purchase
description, embedded at match time in retrieval.py) get the instruction
prefix the model card specifies. Embedding a passage with the query prefix
or vice versa measurably lowers cosine similarity, so the two call sites are
not interchangeable and both must use this same model and this same prefix
convention or the vectors stop meaning the same thing.

Attempted on Lightning AI first, as instructed: Sandbox.create() reaches the
control plane (the scoped LIGHTNING_API_KEY resolves fine for that call) but
the teamspace's balance is $0.01 with free credits disabled, so the API
replies 400 INSUFFICIENT_BALANCE before a machine ever boots. Job.run()
additionally cannot resolve a teamspace at all: the same key gets a 403
"unauthorized" from projects_service_get_project, the endpoint the SDK uses
internally to turn "owner/teamspace" into a project id. Neither is a code
problem this script can work around; both are evidenced in the retrieval.py
module docstring. 739 recalls at 384 dimensions is small enough to embed on
this machine's own hardware, so the build below runs locally on Apple
Silicon MPS (falling back to CPU if MPS is unavailable) instead.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.feeds import cpsc, nhtsa, openfda  # noqa: E402
from agent.feeds.base import Recall  # noqa: E402

DATA = Path(__file__).parent.parent / "data"
INDEX_DIR = DATA / "index"
MODEL_NAME = "BAAI/bge-small-en-v1.5"
QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


def _passage_text(recall: Recall) -> str:
    hazards = " ".join(recall.hazards)
    return f"{recall.title} {recall.description} {hazards}".strip()


def load_all_recalls() -> list[Recall]:
    """Every recall notice captured in data/, across all three feeds.

    CPSC's file is a bare JSON array (the raw saferproducts.gov response).
    openFDA's sample is {"food": {...}, "drug": {...}, "device": {...}},
    one raw enforcement.json response object per endpoint, each holding a
    "results" array. NHTSA's sample is one raw recallsByVehicle response,
    also under "results". Each feed's own parse_recall turns its native
    payload shape into the shared Recall dataclass.
    """
    recalls: list[Recall] = []

    cpsc_raw = json.loads((DATA / "cpsc_2026.json").read_text())
    recalls.extend(cpsc.parse_recall(item) for item in cpsc_raw)

    openfda_raw: dict[str, Any] = json.loads((DATA / "openfda_sample.json").read_text())
    for endpoint_body in openfda_raw.values():
        recalls.extend(openfda.parse_recall(item) for item in endpoint_body.get("results", []))

    nhtsa_raw: dict[str, Any] = json.loads((DATA / "nhtsa_sample.json").read_text())
    recalls.extend(nhtsa.parse_recall(item) for item in nhtsa_raw.get("results", []))

    return recalls


def build(recalls: list[Recall]) -> None:
    from sentence_transformers import SentenceTransformer
    import torch

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"loading {MODEL_NAME} on {device}")
    model = SentenceTransformer(MODEL_NAME, device=device)

    texts = [_passage_text(r) for r in recalls]
    empty = sum(1 for t in texts if not t)
    if empty:
        print(f"warning: {empty} recalls have no title/description/hazard text to embed")

    started = time.monotonic()
    vectors = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
        convert_to_numpy=True,
    ).astype(np.float32)
    elapsed = time.monotonic() - started
    print(f"encoded {len(texts)} passages in {elapsed:.1f}s on {device}")

    ids = [f"{r.source}|{r.recall_number}" for r in recalls]
    sources = [r.source for r in recalls]

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    npz_path = INDEX_DIR / "recalls.npz"
    np.savez_compressed(npz_path, vectors=vectors, ids=np.array(ids))

    sidecar = {
        "model": MODEL_NAME,
        "query_instruction": QUERY_INSTRUCTION,
        "dim": int(vectors.shape[1]),
        "count": len(ids),
        "device_used_for_build": device,
        "build_seconds": round(elapsed, 1),
        "counts_by_source": {s: sources.count(s) for s in sorted(set(sources))},
        "ids": ids,
    }
    sidecar_path = INDEX_DIR / "recalls.json"
    sidecar_path.write_text(json.dumps(sidecar, indent=2))

    npz_size = npz_path.stat().st_size
    print(f"wrote {npz_path} ({npz_size / 1024:.0f} KB) and {sidecar_path}")


def main() -> None:
    recalls = load_all_recalls()
    print(f"loaded {len(recalls)} recalls: "
          f"{sum(1 for r in recalls if r.source == 'CPSC')} CPSC, "
          f"{sum(1 for r in recalls if r.source == 'openFDA')} openFDA, "
          f"{sum(1 for r in recalls if r.source == 'NHTSA')} NHTSA")
    build(recalls)


if __name__ == "__main__":
    main()
