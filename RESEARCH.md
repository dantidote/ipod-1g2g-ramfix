# Technical summary

Names below describe inferred roles rather than recovered Apple symbols. Addresses are relative to the OSOS payload; in the supported pre-install container, OSOS begins at file offset `0x4400`.

## The leak

The allocator at OSOS `0x34d20` creates two allocations: a small handle and a backing buffer. The handle stores a data pointer, capacity, and length.

The growth function at `0x34d90` allocates larger storage, copies the old contents, and calls the disposer at `0x34c98`. The original disposer releases the small handle but leaves its backing buffer allocated. Repeated growth of the library's string data and index tables therefore accumulates abandoned allocations. String-pool disposal uses the same helper.

The database loader already reads incrementally. Its parsed tracks and metadata remain in memory; some repeated metadata is already shared. This patch addresses the abandoned allocations rather than redesigning the database format.

## The replacement

The first 12 bytes of the 32-byte disposal routine contain the original null-handle behavior and remain in the user's firmware. The replacement occupies the remaining 20 bytes, beginning at OSOS `0x34ca4` / container offset `0x390a4`:

```asm
push {r0, lr}
ldr  r0, [r0]
bl   0x34cfc
pop  {r0, lr}
b    0x34cfc
```

It saves the handle and return address, frees the owned backing allocation through an existing wrapper, restores the handle and return address, then tail-calls that wrapper to release the handle. The wrapper preserves the registers required by the original interface and returns zero. The original null-handle path still returns -50. Maximum nested stack use increases by eight bytes.

The patch uses ARMv4T instructions and fits in the existing routine. Code location, OSOS length, and payload layout remain unchanged. The OSOS additive checksum changes from `0x114bd398` to `0x114bd122`; the checksum words at container offsets `0x401c` and `0x421c` are updated. The AUPD/ROM-update payload is unchanged.

## Ownership review

An aligned ARM branch scan found eight direct calls to the disposer: `0x33740`, `0x3374c`, `0x33758`, `0x34e0c`, `0xb22c0`, `0xc53d8`, `0xf70a4`, and `0xf7dbc`. Inspected paths own the handles they release: string-pool tables, the old copied growth allocation, a generic array, a temporary copied handle, and resource objects/failure cleanup.

Copies inspected in these paths allocate distinct backing storage. The separate resize helper updates a handle after releasing its previous backing allocation, so later disposal releases the current buffer. No intentional borrowed backing pointer was found in the inspected direct-call paths. The scan is not an exhaustive proof about all possible indirect references or higher-level lifetime behavior.

## Evidence and limits

| Isolated title pool | Original | Patched |
|---|---:|---:|
| 9,000 titles of 40 UTF-16LE bytes each | 14,978,256 allocated bytes | 440,168 allocated bytes |
| Allocated bytes after pool disposal | 14,978,224 | 0 |

Every retained string is checked byte-for-byte. Further tests exercise repeated 20,000-string pools, shared-string reference counts and compaction, both growth-allocation failure paths, register/stack preservation, independent copies, and cleanup. Observation hooks compare native live allocations with the native heap counter and reject invalid/double frees in exercised paths. Nearly whole-heap allocations after cleanup check that freed blocks coalesce.

The generated firmware hash matches the earlier build used in the physical trial. One owner subsequently reported that their 13,000-song library could be browsed, played, shuffled, and reshuffled. Startup and full-library shuffle remained slow. There are no measured hardware RAM figures or startup timings, and no claim of long-term stability or support for every first/second-generation unit.
