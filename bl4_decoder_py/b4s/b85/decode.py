from bl4_decoder_py.lib.byte_mirror import UINT8_MIRROR

B85_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#$%&()*+-;<=>?@^_`{/}~"
B85_PADDING_CHAR = '~'
B85_PADDING_VALUE = 84  # Value of '~' in the charset

REVERSE_LOOKUP = [-1] * 256
for i, char in enumerate(B85_CHARSET):
    REVERSE_LOOKUP[ord(char)] = i

def decode(serial: str) -> bytes:
    if not serial.startswith("@U"):
        raise ValueError("Not a valid Borderlands 4 item serial")
    
    serial = serial[2:]
    
    result = bytearray()
    idx = 0
    size = len(serial)
    
    while idx < size:
        v = 0
        char_count = 0
        
        # Collect up to 5 valid Base85 characters
        temp_idx = idx
        for _ in range(5):
            if temp_idx < size:
                char_code = ord(serial[temp_idx])
                if 0 <= REVERSE_LOOKUP[char_code] < 85:
                    v = v * 85 + REVERSE_LOOKUP[char_code]
                    char_count += 1
                temp_idx += 1
            else:
                break
        idx = temp_idx

        if char_count == 0:
            break
            
        # Handle padding for incomplete groups
        if char_count < 5:
            padding = 5 - char_count
            for _ in range(padding):
                v = v * 85 + B85_PADDING_VALUE

        # Extract bytes
        byte_count = 4
        if char_count < 5:
            byte_count = char_count - 1

        if byte_count >= 1:
            result.append((v >> 24) & 0xFF)
        if byte_count >= 2:
            result.append((v >> 16) & 0xFF)
        if byte_count >= 3:
            result.append((v >> 8) & 0xFF)
        if byte_count >= 4:
            result.append(v & 0xFF)

    # Mirror the bits in each byte
    mirrored_result = bytearray(len(result))
    for i, byte in enumerate(result):
        mirrored_result[i] = UINT8_MIRROR[byte]
        
    return bytes(mirrored_result)
