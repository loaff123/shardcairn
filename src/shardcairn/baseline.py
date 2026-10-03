"""Exclusive-cost LPT; independent verifier has a separate implementation."""
import heapq


def baseline_vector(manifest):
    n, k = len(manifest.units), manifest.shards
    order = sorted(range(n), key=lambda i: (-manifest.units[i].exclusive_cost_ms, i))
    vector = [0] * n
    heap = []
    for shard, i in enumerate(order[:k]):
        vector[i] = shard
        heap.append((manifest.units[i].exclusive_cost_ms, shard))
    heapq.heapify(heap)
    for i in order[k:]:
        load, shard = heapq.heappop(heap)
        vector[i] = shard
        heapq.heappush(heap, (load + manifest.units[i].exclusive_cost_ms, shard))
    mapping = {}
    return tuple(mapping.setdefault(s, len(mapping)) for s in vector)
