from bl4_decoder_py.b4s.b85.decode import B85_CHARSET
from bl4_decoder_py.lib.byte_mirror import UINT8_MIRROR

_85_1 = 85
_85_2 = 85 * 85
_85_3 = 85 * 85 * 85
_85_4 = 85 * 85 * 85 * 85

def encode(data: bytearray) -> str:
    bytes_mirrored = bytearray(len(data))
    for i in range(len(data)):
        bytes_mirrored[i] = UINT8_MIRROR[data[i]]

    result = []
    idx = 0
    length = len(bytes_mirrored)
    extra_bytes = length % 4
    full_groups = length // 4

    for _ in range(full_groups):
        v = (bytes_mirrored[idx] << 24) | (bytes_mirrored[idx+1] << 16) | \
            (bytes_mirrored[idx+2] << 8) | bytes_mirrored[idx+3]
        idx += 4

        result.append(B85_CHARSET[v // _85_4])
        v %= _85_4
        result.append(B85_CHARSET[v // _85_3])
        v %= _85_3
        result.append(B85_CHARSET[v // _85_2])
        v %= _85_2
        result.append(B85_CHARSET[v // _85_1])
        result.append(B85_CHARSET[v % _85_1])

    if extra_bytes != 0:
        v = bytes_mirrored[idx]
        if extra_bytes >= 2:
            v = (v << 8) | bytes_mirrored[idx+1]
        if extra_bytes == 3:
            v = (v << 8) | bytes_mirrored[idx+2]
            
        if extra_bytes == 3:
            v <<= 8
        elif extra_bytes == 2:
            v <<= 16
        else:
            v <<= 24
            
        result.append(B85_CHARSET[v // _85_4])
        v %= _85_4
        result.append(B85_CHARSET[v // _85_3])

        if extra_bytes >= 2:
            v %= _85_3
            result.append(B85_CHARSET[v // _85_2])
            
            if extra_bytes == 3:
                v %= _85_2
                result.append(B85_CHARSET[v // _85_1])
                
    return "@U" + "".join(result)
