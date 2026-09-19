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

## Earlier firmware comparison — September 19, 2026

The ten older images examined do **not** have this particular handle-growth leak.
Their constructor makes one allocation containing an eight-byte header followed
by its data; the data pointer is `handle + 8`. Freeing the handle therefore frees
both header and data. The 1.5 constructor instead allocates a handle and a separate
data buffer, while its disposer still frees only the handle. This explains why
the same-looking disposal routine is correct in the older releases and leaks
in 1.5. The representation change is observed in the binaries; Apple's reason
for changing it is unknown.

| Firmware image | OSOS disposer offset | Allocation layout | Live allocations after cleanup |
|---|---:|---|---:|
| 1.0 | `0x31d80` | One contiguous block | 0 |
| 1.0.2 | `0x31d80` | One contiguous block | 0 |
| 1.0.4 | `0x31d80` | One contiguous block | 0 |
| 1.1 | `0x2dd88` | One contiguous block | 0 |
| 1.2 | `0x34088` | One contiguous block | 0 |
| 1.2.1 | `0x340a0` | One contiguous block | 0 |
| 1.2.2 | `0x340b4` | One contiguous block | 0 |
| 1.2.6 | `0x34110` | One contiguous block | 0 |
| 1.3 | `0x34728` | One contiguous block | 0 |
| 1.4 | `0x34728` | One contiguous block | 0 |
| 1.5, stock | `0x34c98` | Separate handle and data | 27 |
| 1.5, RAM fix v1 | `0x34c98` | Separate handle and data | 0 |

These results use three growth/cleanup cycles with nine growth steps per cycle.
Stock 1.5 leaves 27 data allocations holding 148,527 requested bytes. All ten
older images and patched 1.5 return to zero live allocations. The test checks
every retained byte, null disposal, each constructor allocation-failure path,
callee-saved registers, stack balance, and invalid/double frees.

The comparison executes each image's actual ARM constructor, growth, copy, and
disposal routines. Native copy helpers are relocated using that image's own
startup table. Only the underlying heap allocation/free calls are replaced with
strict tracking callbacks. Thus these figures describe ownership and requested
storage, **not** native heap overhead, a full firmware boot, or a song-count
capacity test. The earlier native-heap title-pool tests above remain separate.

The eleven input images were checked against the
[flashpod firmware catalog](https://github.com/davidbarnhart/flashpod/blob/main/flashpod/firmware/firmware.json).
Exact container and OSOS hashes are recorded in
[`firmware-audit-profiles.json`](firmware-audit-profiles.json); results are in
[`firmware-audit-results.json`](firmware-audit-results.json). The catalog uses
`0.0`, `0.2`, and `0.4` for the images labeled 1.0, 1.0.2, and 1.0.4 here, and
those early containers are repacks. The conclusions apply to the recorded OSOS
payloads. **1.0.3 was not examined because an image was unavailable in this
corpus.** This is not a claim to have examined every historical build or variant.

Do not apply the 1.5 patch to these older images. Their data pointer points inside
the handle's allocation, so separately freeing it would be invalid; the 1.5
replacement's branch targets also do not match their routine layout. The
installer's 1.5 hash restrictions remain intentional. These results do not show
that older firmware supports any particular large-library size or is free from
other memory limits.

### Reproduce the comparison

Install `unicorn==2.1.4`, then supply your own matching raw or gzip firmware files:

```sh
python audit_firmware_versions.py firmware-1.4.bin.gz firmware-1.5.bin.gz --json audit.json
```

Pass additional filenames to test more versions. The script rejects unknown
container hashes, does not download firmware, does not access devices, and does
not write firmware. For the supported stock 1.5 input it also tests the existing
v1 patch in emulator memory. The JSON output refuses to overwrite an existing
file. No Apple firmware or original routine bytes are included in the audit
script, profiles, or results.
