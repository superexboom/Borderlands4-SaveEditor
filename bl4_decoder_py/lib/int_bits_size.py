def int_bits_size(value: int, min_val: int = 0, max_val: int = 0) -> int:
    i = min_val
    while True:
        if (1 << i) > value:
            return i
        if max_val > 0 and i == max_val:
            return i
        i += 1
