"""Apply, reverse, or verify RAM fix v1 for one exact iPod firmware image.

Public source distribution: no firmware image or original routine bytes included.
Python 3 standard library only. Operates on user-supplied local firmware files.
No firmware downloads or device operations. Reversal requires your original file.
Supported source: iPod_1.1.5_2005_02_18.bin.gz (family 1, software 1.5).
The output retains the source's pre-install directory state. Use an installer
that applies the normal directory fixups; do not write it directly to a disk.
"""
import argparse
import gzip
import hashlib
import io
import json
import struct
from pathlib import Path

RAW_SIZE = 5068800
ORIGINAL_SHA256 = 'af3950c2253dfd0a9f743440f01634ddb8ce018115c05d9ca0e675912202a3df'
PATCHED_SHA256 = '59b584ecffbbc802315ed506cd75bba130ec9797d6aa6c6379d80c335cc6300e'
OSOS_START, OSOS_SIZE = 0x4400, 0x315aa8
CODE_OFFSET, CODE_ADDRESS = 0x39098, 0x34c98
CHECKSUM_OFFSETS = (0x401c, 0x421c)
ORIGINAL_CHECKSUM, PATCHED_CHECKSUM = 0x114bd398, 0x114bd122
# Only the five replacement instructions are distributed. The unchanged
# null-handle checks stay in the user's original firmware.
PATCH_OFFSET = CODE_OFFSET + 12
PATCHED_CODE = bytes.fromhex('01402de9 000090e5 120000eb 0140bde8 100000ea')


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def load(path):
    path = Path(path)
    if not path.is_file():
        raise ValueError('Input must be a regular firmware file.')
    with path.open('rb') as source:
        if source.read(2) == b'\x1f\x8b':
            source.seek(0)
            with gzip.GzipFile(fileobj=source, mode='rb') as compressed:
                raw = compressed.read(RAW_SIZE + 1)
        else:
            source.seek(0)
            raw = source.read(RAW_SIZE + 1)
    verify(raw)
    return raw


def verify(raw):
    digest = sha256(raw)
    if len(raw) != RAW_SIZE or digest not in (ORIGINAL_SHA256, PATCHED_SHA256):
        raise ValueError('Unsupported or altered firmware (SHA-256: %s). '
                         'This patch accepts only the exact original or RAM-fix-v1 image.' % digest)
    patched = digest == PATCHED_SHA256
    checksum = PATCHED_CHECKSUM if patched else ORIGINAL_CHECKSUM
    if patched and raw[PATCH_OFFSET:PATCH_OFFSET+20] != PATCHED_CODE:
        raise ValueError('Unexpected replacement instructions at the patch site.')
    if raw[:4] != b'{{~~' or raw[0x100:0x104] != b']ih[':
        raise ValueError('Invalid firmware header.')
    if struct.unpack_from('<I', raw, 0x104)[0] != 0x4000:
        raise ValueError('Unexpected directory location.')
    if struct.unpack_from('<H', raw, 0x10a)[0] != 2:
        raise ValueError('Unexpected container format.')
    actual = sum(raw[OSOS_START:OSOS_START+OSOS_SIZE]) & 0xffffffff
    if actual != checksum:
        raise ValueError('OSOS payload checksum mismatch.')
    for directory in (0x4000, 0x4200):
        if raw[directory:directory+8] != b'!ATAsoso':
            raise ValueError('Unexpected OSOS directory entry.')
        if struct.unpack_from('<I', raw, directory+28)[0] != checksum:
            raise ValueError('OSOS directory checksum mismatch.')
    return {'state': 'ramfix-v1' if patched else 'original',
            'raw_sha256': digest, 'raw_size_bytes': len(raw),
            'osos_checksum': '0x%08x' % checksum,
            'container_state': 'pre-install; installer directory fixups required'}


def transform(raw, revert=False, original=None):
    info = verify(raw)
    required = 'ramfix-v1' if revert else 'original'
    if info['state'] != required:
        raise ValueError('Expected %s input; got %s. No output written.' % (required, info['state']))
    if revert:
        if original is None:
            raise ValueError('Reversal requires your original firmware file; none is bundled.')
        if verify(original)['state'] != 'original':
            raise ValueError('Reversal reference must be the supported original firmware.')
        if transform(original) != raw:
            raise ValueError('Original reference does not reproduce this patched image.')
        return bytes(original)
    result = bytearray(raw)
    result[PATCH_OFFSET:PATCH_OFFSET+20] = PATCHED_CODE
    checksum = sum(result[OSOS_START:OSOS_START+OSOS_SIZE]) & 0xffffffff
    for offset in CHECKSUM_OFFSETS:
        struct.pack_into('<I', result, offset, checksum)
    result = bytes(result)
    expected = PATCHED_SHA256
    if sha256(result) != expected:
        raise ValueError('Internal error: output SHA-256 mismatch.')
    verify(result)
    return result


def encode(raw, compressed):
    if not compressed:
        return raw
    buf = io.BytesIO()
    # No filename or timestamp: reproducible gzip header.
    with gzip.GzipFile(filename='', fileobj=buf, mode='wb', compresslevel=9, mtime=0) as archive:
        archive.write(raw)
    return buf.getvalue()


def write_new(path, raw):
    path = Path(path)
    if not (path.name.endswith('.bin') or path.name.endswith('.bin.gz')):
        raise ValueError('Output filename must end in .bin or .bin.gz.')
    data = encode(raw, path.name.endswith('.gz'))
    # Exclusive creation prevents overwriting either the input or any existing file.
    with path.open('xb') as dest:
        dest.write(data)
    return {'output': str(path.resolve()), 'file_sha256': sha256(data),
            'file_size_bytes': len(data), **verify(raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('apply', 'revert', 'verify'):
        sub = commands.add_parser(name)
        sub.add_argument('input', type=Path)
        if name != 'verify':
            sub.add_argument('output', type=Path)
        if name == 'revert':
            sub.add_argument('--original', type=Path, required=True,
                             help='Your matching original firmware file (raw or gzip)')
    args = parser.parse_args()
    try:
        raw = load(args.input)
        if args.command == 'verify':
            result = verify(raw)
        else:
            reference = load(args.original) if args.command == 'revert' else None
            result = write_new(args.output, transform(raw, args.command == 'revert', reference))
    except (ValueError, OSError, EOFError) as error:
        parser.exit(2, 'Error: %s\n' % error)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
