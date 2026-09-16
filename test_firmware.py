"""Test user-supplied original and patched firmware using their ARM routines in Unicorn.

Requires: Python 3 and unicorn==2.1.4
Usage: python test_firmware.py original.bin.gz patched.bin.gz --json results.json
Optional: --flashpod-source /path/to/flashpod (test its file loader, no device I/O)
This is isolated routine testing, not a full boot or a hardware test.
"""
import argparse
import gzip
import json
import struct
import sys
import tempfile
from pathlib import Path

import unicorn
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (
    UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
    UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
    UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
)
import patch_firmware as patch

STOP, GLOBAL, SLOT, STACK = 0x150000, 0x3e0854, 0x800000, 0xf00000
HEAP_START, HEAP_SIZE = 0x1000000, 0x1000000
ARGS = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3]
PRESERVED = [UC_ARM_REG_R3, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6,
             UC_ARM_REG_R7, UC_ARM_REG_R8, UC_ARM_REG_R9,
             UC_ARM_REG_R10, UC_ARM_REG_R11]


def check(condition, message):
    if not condition:
        raise AssertionError(message)


class Machine:
    def __init__(self, payload):
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.live_allocations = {}
        self.frees = []
        u.mem_map(0, 0x2000000)
        u.mem_write(0, payload)
        # Relocations from this firmware's own startup table.
        u.mem_write(0x380000, payload[0x2ec784:0x2ec784 + 0xc400])
        u.mem_map(0x40000000, 0x20000)
        u.mem_write(0x40000170, payload[0x2fcfb4:0x2fcfb4 + 0x534])

        def bypass_lock(uc, address, size, user):
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        # Single-thread harness: bypass synchronization only. All allocator,
        # copier and pool instructions execute from the supplied firmware.
        u.hook_add(UC_HOOK_CODE, bypass_lock, begin=0x3b38, end=0x3b38)
        u.hook_add(UC_HOOK_CODE, bypass_lock, begin=0x6348, end=0x6348)

        def observe_allocation(uc, address, size, user):
            header = uc.reg_read(UC_ARM_REG_R5)
            pointer = header + 4
            check(pointer not in self.live_allocations, 'Allocation overlaps a live block')
            self.live_allocations[pointer] = self.read32(header) & 0x3ffffffc

        def observe_free(uc, address, size, user):
            pointer = uc.reg_read(UC_ARM_REG_R0)
            if pointer:
                check(pointer in self.live_allocations, 'Invalid or double free: %#x' % pointer)
                del self.live_allocations[pointer]
            self.frees.append(pointer)

        # Observation hooks do not alter code or registers.
        u.hook_add(UC_HOOK_CODE, observe_allocation, begin=0x4068, end=0x4068)
        u.hook_add(UC_HOOK_CODE, observe_free, begin=0x3e14, end=0x3e14)
        u.mem_write(GLOBAL + 2, b'\x01')  # Use the explicit test heap.
        self.call(0x3d40, HEAP_START, HEAP_SIZE)
        self.initial = self.stats()

    def read32(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def write32(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value))

    def stats(self):
        result = {'free_bytes': self.read32(GLOBAL + 4),
                  'used_bytes': self.read32(GLOBAL + 8)}
        check(sum(self.live_allocations.values()) == result['used_bytes'],
              'Observed allocations disagree with native heap accounting')
        return result

    def call(self, address, *args):
        for register, value in zip(ARGS, args):
            self.u.reg_write(register, value)
        self.u.reg_write(UC_ARM_REG_SP, STACK)
        self.u.reg_write(UC_ARM_REG_LR, STOP)
        self.u.emu_start(address, STOP, count=50000000)
        check(self.u.reg_read(UC_ARM_REG_PC) == STOP, 'Execution limit reached')
        check(self.u.reg_read(UC_ARM_REG_SP) == STACK, 'Stack not restored')
        return self.u.reg_read(UC_ARM_REG_R0)

    def clean(self):
        check(self.stats() == self.initial, 'Heap did not return to its initial state')
        check(not self.live_allocations, 'Live allocations remain after cleanup')
        # Prove freed blocks coalesced: allocate nearly the whole heap at once.
        filler = self.call(0x34d10, self.initial['free_bytes']-4)
        check(filler != 0 and self.stats()['free_bytes'] == 0, 'Heap is fragmented')
        check(self.call(0x34cfc, filler) == 0, 'Filler disposal failed')
        check(self.stats() == self.initial, 'Heap accounting changed after coalescence test')


def title(n):
    return ('Track %014d' % n).encode('utf-16le')


def insert(e, value, pool=SLOT):
    e.u.mem_write(SLOT+0x1000, value)
    check(e.call(0x33848, pool, SLOT+0x1000, len(value), SLOT+0x2000) == 0,
          'String insertion failed')
    return e.read32(SLOT+0x2000)


def read_string(e, index, pool=SLOT):
    table = e.read32(e.read32(pool+8))
    data = e.read32(e.read32(pool+0x10))
    offset, length = struct.unpack('<II', e.u.mem_read(table+(index-1)*8, 8))
    check(offset != 0xffffffff, 'Reading an unused string entry')
    return bytes(e.u.mem_read(data+offset, length))


def titles_test(payload, count, fixed, cycles=1, varied=False):
    e = Machine(payload)
    steps = []
    for cycle in range(cycles):
        check(e.call(0x336ec, SLOT, 0) == 0, 'Pool initialization failed')
        values = []
        for n in range(1, count+1):
            value = (('曲 Café \U0001f3b5 %d ' % n + 'x'*(n % 61)).encode('utf-16le')
                     if varied else title(n))
            values.append(value)
            check(insert(e, value) == n, 'Unexpected string index')
            if n in (1000, 3000, 5000, 7000, 9000, count):
                steps.append({'cycle': cycle+1, 'strings': n, **e.stats()})
        for n, value in enumerate(values, 1):
            check(read_string(e, n) == value, 'Retained string differs from input')
        check(e.call(0x3371c, SLOT) == 0, 'Pool cleanup failed')
        if fixed:
            e.clean()
    return {'strings_per_cycle': count, 'cycles': cycles,
            'all_strings_verified': True, 'steps': steps,
            'after_dispose': e.stats(), 'allocation_observer_passed': True}


def handles_test(payload):
    e = Machine(payload)
    check(e.call(0x34c98, 0) == 0xffffffce, 'Null-handle return changed')
    check(not e.frees, 'Null handle reached allocator')
    handle = e.call(0x34d20, 8192, 1)
    check(handle != 0, 'Handle allocation failed')
    data = e.read32(handle)
    check(bytes(e.u.mem_read(data, 8192)) == bytes(8192), 'Zeroed allocation changed')
    for i, reg in enumerate(PRESERVED):
        e.u.reg_write(reg, 0x12345000+i)
    check(e.call(0x34c98, handle) == 0, 'Disposal return changed')
    check(e.frees[-2:] == [data, handle], 'Must free backing allocation before handle')
    for i, reg in enumerate(PRESERVED):
        check(e.u.reg_read(reg) == 0x12345000+i, 'Preserved register changed')
    e.clean()
    # Owned handle with a null backing pointer: native free(NULL) remains valid.
    handle = e.call(0x34d10, 12)
    e.u.mem_write(handle, bytes(12))
    check(e.call(0x34c98, handle) == 0, 'Null backing pointer failed')
    e.clean()
    # Normal allocations at allocator alignment boundaries, including zero size.
    for size in (0, 1, 3, 4, 11, 12, 13, 15, 16, 17, 4095, 4096, 4097):
        for zeroed in (0, 1):
            handle = e.call(0x34d20, size, zeroed)
            check(handle != 0, 'Boundary allocation failed')
            check(e.call(0x34c98, handle) == 0, 'Boundary disposal failed')
    e.clean()
    return {'null_returns_minus_50': True, 'backing_then_handle_free': True,
            'stack_and_registers_preserved': True, 'boundary_allocations': 26,
            'after_dispose': e.stats()}


def growth_and_failure_test(payload):
    e = Machine(payload)
    pattern = bytes(range(256))*16
    for n in range(1, 9):
        check(e.call(0x34d90, SLOT, 4096) == 1, 'Growth failed')
        handle = e.read32(SLOT)
        data = e.read32(handle)
        check(bytes(e.u.mem_read(data, 4096*(n-1))) == pattern*(n-1), 'Growth lost data')
        e.u.mem_write(data+4096*(n-1), pattern)
    before = e.stats()
    # New handle succeeds, new backing allocation fails; temporary handle freed.
    check(e.call(0x34d90, SLOT, 0x1400000) == 0, 'Oversized growth succeeded')
    check(e.read32(SLOT) == handle and e.stats() == before, 'Backing failure changed state')
    check(bytes(e.u.mem_read(data, 32768)) == pattern*8, 'Backing failure lost data')
    check(e.call(0x34c98, handle) == 0, 'Handle free failed')
    e.clean()
    # Exhaust the heap so even allocating the replacement handle fails.
    # Use a fresh heap so the free area is contiguous before filling it.
    e = Machine(payload)
    check(e.call(0x34d90, SLOT, 4096) == 1, 'Initial growth failed')
    handle = e.read32(SLOT)
    data = e.read32(handle)
    e.u.mem_write(data, pattern)
    before = e.stats()
    filler = e.call(0x34d10, before['free_bytes']-4)
    check(filler != 0 and e.stats()['free_bytes'] == 0, 'Heap exhaustion setup failed')
    full = e.stats()
    check(e.call(0x34d90, SLOT, 4096) == 0, 'Exhausted growth succeeded')
    check(e.read32(SLOT) == handle and e.stats() == full, 'Handle failure changed state')
    check(bytes(e.u.mem_read(data, 4096)) == pattern, 'Failure lost retained data')
    check(e.call(0x34cfc, filler) == 0, 'Filler free failed')
    check(e.call(0x34c98, handle) == 0, 'Handle free failed')
    e.clean()
    return {'growth_copy_verified': True, 'both_allocation_failure_paths_verified': True,
            'after_dispose': e.stats()}


def shared_pool_test(payload):
    e = Machine(payload)
    check(e.call(0x336ec, SLOT, 1) == 0, 'Shared pool initialization failed')
    values = [('Artist 曲 %03d' % n).encode('utf-16le') for n in range(200)]
    for repeat in range(5):
        for n, value in enumerate(values, 1):
            check(insert(e, value) == n, 'Deduplication returned a different index')
    refs = e.read32(e.read32(SLOT+0xc))
    check([e.read32(refs+4*n) for n in range(200)] == [5]*200, 'Wrong reference counts')
    for repeat in range(4):
        check(e.call(0x33b68, SLOT, 1) == 0, 'Shared removal failed')
        check(read_string(e, 1) == values[0], 'Referenced string removed too early')
    check(e.call(0x33b68, SLOT, 1) == 0, 'Final removal failed')
    check(e.read32(e.read32(e.read32(SLOT+8))) == 0xffffffff, 'Removed entry still active')
    for n in range(2, 201):
        check(read_string(e, n) == values[n-1], 'Compaction damaged another string')
    check(insert(e, values[0]) == 1, 'Removed entry was not reusable')
    check(read_string(e, 1) == values[0], 'Reinserted string differs')
    used = e.stats()['used_bytes']
    check(e.call(0x3371c, SLOT) == 0, 'Shared cleanup failed')
    e.clean()
    return {'insertions': 1000, 'unique_strings': 200, 'used_bytes': used,
            'reference_count_and_compaction_verified': True, 'after_dispose': e.stats()}


def other_owners_test(payload):
    e = Machine(payload)
    # Generic array: own, resize, clone, free original, retain clone, free clone.
    check(e.call(0xb214c, 4, 0, 0, SLOT) == 0, 'Array init failed')
    pattern = bytes(range(128))
    check(e.call(0xb2430, SLOT, 0, 512) == 0, 'Array allocation failed')
    data = e.read32(e.read32(SLOT+0x18))
    e.u.mem_write(data, pattern)
    for size in (8192, 2048, 16384, 128):
        check(e.call(0xb2430, SLOT, 0, size) == 0, 'Array resize failed')
        data = e.read32(e.read32(SLOT+0x18))
        check(bytes(e.u.mem_read(data, 128)) == pattern, 'Resize lost data')
    check(e.call(0xb2200, SLOT, SLOT+0x100) == 0, 'Array clone failed')
    clone_data = e.read32(e.read32(SLOT+0x118))
    check(data != clone_data, 'Clone aliases original storage')
    check(e.call(0xb22b0, SLOT) == 0, 'Original array disposal failed')
    check(bytes(e.u.mem_read(clone_data, 128)) == pattern, 'Clone lost data after original freed')
    check(e.call(0xb22b0, SLOT+0x100) == 0, 'Clone disposal failed')
    e.clean()
    # Copy a caller-owned byte buffer into a new handle, then clone that handle.
    e.u.mem_write(SLOT+0x1000, pattern)
    check(e.call(0x34f74, SLOT+0x1000, SLOT, 128) == 0, 'Copy-to-handle failed')
    original = e.read32(SLOT)
    check(e.call(0x34fc8, SLOT) == 0, 'Handle clone failed')
    clone = e.read32(SLOT)
    check(e.read32(original) != e.read32(clone), 'Handle clone aliases backing storage')
    check(e.call(0x34c98, original) == 0, 'Original handle disposal failed')
    check(bytes(e.u.mem_read(e.read32(clone), 128)) == pattern, 'Handle clone lost data')
    check(e.call(0x34c98, clone) == 0, 'Cloned handle disposal failed')
    e.clean()
    # Resource object constructor, copy operation, and disposal wrapper.
    check(e.call(0xf702c, SLOT) == 0, 'Resource constructor failed')
    resource = e.read32(SLOT)
    check(e.call(0xf7c74, resource, 0, SLOT+4) == 0, 'Resource copy failed')
    resource_copy = e.read32(SLOT+4)
    check(e.read32(resource) != e.read32(resource_copy), 'Resource copy aliases storage')
    header = bytes(e.u.mem_read(e.read32(resource_copy), 32))
    check(e.call(0xf7090, resource) == 0, 'Resource dispose failed')
    check(bytes(e.u.mem_read(e.read32(resource_copy), 32)) == header, 'Resource copy lost data')
    check(e.call(0xf7090, resource_copy) == 0, 'Resource copy dispose failed')
    e.clean()
    return {'array_resize_and_copy_verified': True, 'handle_copy_verified': True,
            'resource_constructor_copy_and_disposal_verified': True, 'after_dispose': e.stats()}


def expect_value_error(fn):
    try:
        fn()
    except ValueError:
        return
    raise AssertionError('Invalid input was accepted')


def container_test(original, patched):
    check(patch.transform(original) == patched, 'Supplied image differs from patcher output')
    check(patch.transform(patched, revert=True, original=original) == original,
          'Reverse patch differs from original')
    expect_value_error(lambda: patch.transform(patched, revert=True))
    expect_value_error(lambda: patch.transform(patched, revert=True, original=patched))
    expect_value_error(lambda: patch.transform(patched, revert=True, original=original[:-1]))
    expect_value_error(lambda: patch.transform(patched))
    expect_value_error(lambda: patch.transform(original, revert=True))
    for offset in (0, 0x401c, 0x421c, patch.CODE_OFFSET, 0x31a000):
        corrupt = bytearray(original)
        corrupt[offset] ^= 1
        expect_value_error(lambda: patch.transform(corrupt))
    expect_value_error(lambda: patch.transform(original[:-1]))
    allowed = set(range(patch.CODE_OFFSET, patch.CODE_OFFSET+32))
    for offset in patch.CHECKSUM_OFFSETS:
        allowed.update(range(offset, offset+4))
    changed = [i for i, (a, b) in enumerate(zip(original, patched)) if a != b]
    check(set(changed) <= allowed, 'Unexpected changes outside patch and checksums')
    check(original[0x31a000:] == patched[0x31a000:], 'AUPD payload changed')
    for image in (original, patched):
        for directory in (0x4000, 0x4200):
            ck = struct.unpack_from('<I', image, directory+28)[0]
            check(ck == sum(image[0x4400:0x319ea8]) & 0xffffffff, 'Directory checksum invalid')
        off, length = struct.unpack_from('<II', image, 0x4234)
        ck = struct.unpack_from('<I', image, 0x4244)[0]
        check(sum(image[off:off+length]) & 0xffffffff == ck, 'AUPD checksum invalid')
    with tempfile.TemporaryDirectory(prefix='ipod-ramfix-test-') as folder:
        out = Path(folder)/'patched.bin.gz'
        patch.write_new(out, patched)
        check(patch.load(out) == patched, 'Compressed output failed round trip')
        check(gzip.decompress(out.read_bytes()) == patched, 'Independent decompression differs')
        try:
            patch.write_new(out, original)
        except FileExistsError:
            pass
        else:
            raise AssertionError('Patcher overwrote an existing output')
        check(patch.load(out) == patched, 'Existing output changed')
    return {'changed_bytes': len(changed), 'changed_offsets': [hex(i) for i in changed],
            'exact_reverse_patch': True, 'unsupported_and_corrupt_input_rejected': True,
            'existing_output_preserved': True, 'both_osos_checksums_valid': True,
            'aupd_payload_unchanged_and_checksum_valid': True}


def loader_test(source, image_path, patched):
    sys.path.insert(0, str(Path(source).resolve()))
    from flashpod.ipod_flash import load_firmware, validate_firmware
    installed = load_firmware(str(image_path))
    validate_firmware(installed)
    check(installed[0x4400:] == patched[0x4400:], 'Loader changed payloads')
    for directory in (0x4000, 0x4200):
        check(struct.unpack_from('<I', installed, directory+36)[0] == 0xffffffff,
              'OSOS install state not normalized')
        check(struct.unpack_from('<I', installed, directory+48)[0] == 1,
              'AUPD install state not normalized')
    return {'loader_accepted_image': True, 'payloads_preserved': True,
            'normalized_image_sha256': patch.sha256(installed),
            'loader_source_sha256': patch.sha256((Path(source)/'flashpod/ipod_flash.py').read_bytes()),
            'device_operations_performed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('original', type=Path)
    parser.add_argument('patched', type=Path)
    parser.add_argument('--json', type=Path)
    parser.add_argument('--flashpod-source', type=Path)
    args = parser.parse_args()
    original, patched = patch.load(args.original), patch.load(args.patched)
    check(patch.sha256(original) == patch.ORIGINAL_SHA256, 'First image must be original')
    check(patch.sha256(patched) == patch.PATCHED_SHA256, 'Second image must be RAM fix v1')
    payload = patched[patch.OSOS_START:patch.OSOS_START+patch.OSOS_SIZE]
    old_payload = original[patch.OSOS_START:patch.OSOS_START+patch.OSOS_SIZE]
    results = {'status': 'passed', 'unicorn_version': unicorn.__version__,
               'scope': 'Original and final on-disk ARM routines; chosen 16 MiB heap; '
                        'synchronization bypassed; no full boot, playback, or hardware test.',
               'runtime_code_injection': False,
               'original_raw_sha256': patch.sha256(original),
               'patched_raw_sha256': patch.sha256(patched),
               'container': container_test(original, patched),
               'handle_semantics': handles_test(payload),
               'growth_and_failure': growth_and_failure_test(payload),
               'shared_pool': shared_pool_test(payload),
               'other_owners': other_owners_test(payload),
               'original_9000_titles': titles_test(old_payload, 9000, False),
               'patched_9000_titles': titles_test(payload, 9000, True),
               'patched_20000_varied_titles': titles_test(payload, 20000, True, cycles=3, varied=True)}
    if args.flashpod_source:
        results['flashpod_loader'] = loader_test(args.flashpod_source, args.patched, patched)
    rendered = json.dumps(results, indent=2)+'\n'
    if args.json:
        args.json.write_text(rendered, encoding='utf-8')
    print(rendered)


if __name__ == '__main__':
    main()
