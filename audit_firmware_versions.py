"""Compare this handle leak across exact, user-supplied early-iPod firmware images.

Requires unicorn==2.1.4. No device access, firmware download, or firmware output.
Actual constructor, growth, copy and disposal instructions run in the emulator;
only heap allocation and free are replaced with strict tracking callbacks.
This is an isolated ownership test, not a full boot or native-heap benchmark.
"""
import argparse
import gzip
import hashlib
import io
import json
import struct
import sys
from pathlib import Path

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
    UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7, UC_ARM_REG_R8,
    UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11, UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC)

STOP, STACK, SLOT = 0x700000, 0xf00000, 0x800000
ARGS = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)
PRESERVED = (UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)
from patch_firmware import PATCHED_CODE as PATCH


def destination(payload, offset):
    word = struct.unpack_from('<I', payload, offset)[0]
    assert word & 0x0e000000 == 0x0a000000
    delta = word & 0xffffff
    if delta & 0x800000:
        delta -= 0x1000000
    return offset + 8 + delta * 4


class Machine:
    def __init__(self, row, payload, patched=False):
        assert hashlib.sha256(payload).hexdigest() == row['payload_sha256']
        self.disposer = d = int(row['disposer'], 16)
        self.split = row['representation'] == 'separate'
        assert not patched or self.split
        self.constructor = d + (0x88 if self.split else 0x64)
        self.grow = d + (0xf8 if self.split else 0x88)
        self.length_offset = 8 if self.split else 4
        free = destination(payload, d + 0x14)
        allocators = ({destination(payload, d + 0x7c), destination(payload, d + 0x84)}
                      if self.split else {destination(payload, d + 0x74)})
        self.u = u = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        u.mem_map(0, 0x2000000)
        u.mem_write(0, payload)
        # Load the native memory-copy helpers using this image's startup table.
        relocations = []
        for offset in range(0, len(payload) - 12, 4):
            source, target, length = struct.unpack_from('<3I', payload, offset)
            source -= 0x04000000
            if (target in (0x40000170, 0x4000040c) and 0 <= source < len(payload)
                    and 0 < length < 0x1000 and source + length <= len(payload)):
                relocations.append((source, target, length))
        assert len(relocations) == 1, relocations
        source, target, length = relocations[0]
        u.mem_map(0x40000000, 0x20000)
        u.mem_write(target, payload[source:source + length])
        executed = bytearray(payload)
        if patched:
            u.mem_write(d + 12, PATCH)
            executed[d + 12:d + 12 + len(PATCH)] = PATCH
        self.executed_sha256 = hashlib.sha256(executed).hexdigest()
        self.live, self.allocation_calls, self.frees = {}, 0, []
        self.next_address, self.fail_at = 0x1000000, None

        def allocate(uc, address, size, user):
            self.allocation_calls += 1
            wanted = uc.reg_read(UC_ARM_REG_R0)
            assert 0 <= wanted <= 1024 * 1024
            if self.allocation_calls == self.fail_at:
                pointer = 0
            else:
                pointer = self.next_address
                reserved = (max(wanted, 16) + 31) & ~31
                self.next_address += reserved
                assert self.next_address < 0x2000000
                self.live[pointer] = wanted
                u.mem_write(pointer, bytes(reserved))
            uc.reg_write(UC_ARM_REG_R0, pointer)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        def release(uc, address, size, user):
            pointer = uc.reg_read(UC_ARM_REG_R0)
            if pointer:
                assert pointer in self.live, f'Invalid or double free: {pointer:#x}'
                del self.live[pointer]
            self.frees.append(pointer)
            uc.reg_write(UC_ARM_REG_R0, 0)
            uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

        for address in allocators:
            u.hook_add(UC_HOOK_CODE, allocate, begin=address, end=address)
        u.hook_add(UC_HOOK_CODE, release, begin=free, end=free)

    def read32(self, pointer):
        return struct.unpack('<I', self.u.mem_read(pointer, 4))[0]

    def write32(self, pointer, value):
        self.u.mem_write(pointer, struct.pack('<I', value))

    def call(self, address, *args):
        sentinel = {reg: 0x12340000 + reg for reg in PRESERVED}
        for reg, value in sentinel.items():
            self.u.reg_write(reg, value)
        for reg, value in zip(ARGS, args):
            self.u.reg_write(reg, value)
        self.u.reg_write(UC_ARM_REG_SP, STACK)
        self.u.reg_write(UC_ARM_REG_LR, STOP)
        try:
            self.u.emu_start(address, STOP, count=10000000)
        except Exception as error:
            raise RuntimeError(f'Call {address:#x}, args={args}, PC={self.u.reg_read(UC_ARM_REG_PC):#x}, LR={self.u.reg_read(UC_ARM_REG_LR):#x}') from error
        assert self.u.reg_read(UC_ARM_REG_PC) == STOP, f'Stopped at {self.u.reg_read(UC_ARM_REG_PC):#x}'
        assert self.u.reg_read(UC_ARM_REG_SP) == STACK
        assert all(self.u.reg_read(reg) == value for reg, value in sentinel.items())
        return self.u.reg_read(UC_ARM_REG_R0)


def exercise(row, payload, patched=False):
    m = Machine(row, payload, patched)
    assert m.call(m.disposer, 0) == 0xffffffce
    assert not m.frees
    traces = []
    for cycle in range(3):
        m.write32(SLOT, 0)
        expected = b''
        for growth in (1, 7, 32, 500, 4096, 3, 8192, 64, 1024):
            old_live = dict(m.live)
            old_handle = m.read32(SLOT)
            # Force each possible allocation failure in the actual constructor.
            for nth in range(1, 3 if m.split else 2):
                m.fail_at = m.allocation_calls + nth
                assert m.call(m.grow, SLOT, growth) == 0
                assert m.read32(SLOT) == old_handle
                assert m.live == old_live
            m.fail_at = None
            assert m.call(m.grow, SLOT, growth) == 1
            handle = m.read32(SLOT)
            pointer = m.read32(handle)
            assert m.read32(handle + m.length_offset) == len(expected) + growth
            assert bytes(m.u.mem_read(pointer, len(expected))) == expected
            extra = bytes((i + cycle) % 251 for i in range(growth))
            m.u.mem_write(pointer + len(expected), extra)
            expected += extra
            assert bytes(m.u.mem_read(pointer, len(expected))) == expected
            if not m.split:
                assert pointer == handle + 8 and len(m.live) == 1
            traces.append({'cycle': cycle, 'size': len(expected), 'live_allocations': len(m.live)})
        assert m.call(m.disposer, handle) == 0
        if not m.split or patched:
            assert not m.live
    result = {'version': row['version'], 'patched': patched,
              'representation': 'separate handle and data' if m.split else 'one block: header followed by data',
              'input_payload_sha256': row['payload_sha256'], 'executed_payload_sha256': m.executed_sha256,
              'disposer': hex(m.disposer),
              'growth_steps': len(traces), 'allocation_calls_including_failures': m.allocation_calls,
              'live_allocations_after_cleanup': len(m.live),
              'requested_bytes_remaining': sum(m.live.values()),
              'checks': ['null disposal', 'three growth/cleanup cycles', 'all retained bytes',
                         'constructor allocation failures', 'callee-saved registers', 'stack balance',
                         'invalid/double-free detection'],
              'scope': 'Original ARM constructor/growth/copy/disposal code; heap allocation/free replaced by strict tracking callbacks. Not full boot or hardware testing.'}
    if m.split and not patched:
        assert len(m.live) == 27
    else:
        assert not m.live
    return result


def load_image(path, profiles):
    maximum = 16 * 1024 * 1024
    with path.open('rb') as stream:
        data = stream.read(maximum + 1)
    if len(data) > maximum:
        raise ValueError('Input is too large for a supported firmware image')
    if data[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(maximum + 1)
    digest = hashlib.sha256(data).hexdigest()
    if digest not in profiles:
        raise ValueError('Unknown firmware image SHA-256: ' + digest)
    row = profiles[digest]
    start = row['payload_start']
    payload = data[start:start + row['payload_size']]
    if hashlib.sha256(payload).hexdigest() != row['payload_sha256']:
        raise ValueError('Payload does not match the audited firmware profile')
    return row, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('firmware', nargs='+', type=Path, help='Your original raw or gzip firmware files')
    parser.add_argument('--json', type=Path, help='Write a JSON report, refusing to overwrite an existing file')
    args = parser.parse_args()
    if sys.flags.optimize:
        parser.error('Run without -O so the test assertions remain enabled')
    profiles_path = Path(__file__).with_name('firmware-audit-profiles.json')
    profiles = {row['raw_sha256']: row for row in json.loads(profiles_path.read_text(encoding='utf-8'))}
    results = []
    for path in args.firmware:
        try:
            row, payload = load_image(path, profiles)
        except (OSError, ValueError, EOFError) as error:
            parser.exit(2, 'Error: ' + str(error) + '\n')
        for patched in ((False, True) if row['version'] == '1.5' else (False,)):
            result = exercise(row, payload, patched)
            results.append(result)
            print(json.dumps(result), flush=True)
    if args.json:
        with args.json.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(json.dumps(results, indent=2) + '\n')


if __name__ == '__main__':
    main()
