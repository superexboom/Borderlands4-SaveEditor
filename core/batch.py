"""Bounded offline import batches shared by the converter and iterator."""

import time

from . import b_encoder


def add_serial_lines(controller, lines, flag):
    """Yield (processed, total, successful, failed), including start and finish."""
    total = len(lines)
    success = fail = 0
    last_report = time.monotonic()
    yield 0, total, success, fail
    for offset in range(0, total, 128):
        chunk = lines[offset:offset + 128]
        serials = []
        for line in chunk:
            try:
                if line.strip().startswith('@U'):
                    serial, error = line, None
                else:
                    serial, error = b_encoder.encode_to_base85(line)
                if error or not serial:
                    fail += 1
                else:
                    serials.append(serial)
            except Exception:
                fail += 1
        try:
            results = controller.add_items_to_backpack(serials, flag)
        except Exception:
            results = [None] * len(serials)
        added = sum(path is not None for path in results)
        success += added
        fail += len(serials) - added
        done = offset + len(chunk)
        now = time.monotonic()
        if done == total or now - last_report >= 0.05:
            yield done, total, success, fail
            last_report = now
