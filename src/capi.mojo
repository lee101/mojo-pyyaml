"""Bulk lexical kernels used by the Python YAML parser and emitter."""

from std.sys.info import simd_width_of


comptime BPtr = UnsafePointer[UInt8, AnyOrigin[mut=True]]
comptime IPtr = UnsafePointer[Int64, AnyOrigin[mut=True]]
comptime BYTE_SIMD_WIDTH = simd_width_of[DType.uint8]()


def is_space(c: UInt8) -> Bool:
    return c == UInt8(32) or c == UInt8(9) or c == UInt8(13)


def scan_line_metadata(
    source: BPtr,
    starts: IPtr,
    ends: IPtr,
    indents: IPtr,
    content_ends: IPtr,
    line: Int,
):
    var start = Int(starts[line])
    var end = Int(ends[line])
    var indent = 0
    while start + indent + BYTE_SIMD_WIDTH <= end:
        var chunk = source.load[width=BYTE_SIMD_WIDTH, alignment=1](start + indent)
        if not chunk.eq(UInt8(32)).reduce_and():
            break
        indent += BYTE_SIMD_WIDTH
    while start + indent < end and source[start + indent] == UInt8(32):
        indent += 1
    var trimmed = end
    while trimmed - BYTE_SIMD_WIDTH >= start + indent:
        var chunk = source.load[width=BYTE_SIMD_WIDTH, alignment=1](trimmed - BYTE_SIMD_WIDTH)
        var spaces = (
            chunk.eq(UInt8(32)) |
            chunk.eq(UInt8(9)) |
            chunk.eq(UInt8(13))
        )
        if not spaces.reduce_and():
            break
        trimmed -= BYTE_SIMD_WIDTH
    while trimmed > start + indent and is_space(source[trimmed - 1]):
        trimmed -= 1
    indents[line] = Int64(indent)
    content_ends[line] = Int64(trimmed)


@export("mpy_scan_lines")
def scan_lines(
    source_addr: Int,
    n: Int,
    starts_addr: Int,
    ends_addr: Int,
    indents_addr: Int,
    content_ends_addr: Int,
    capacity: Int,
) abi("C") -> Int:
    if n < 0 or capacity < 1 or source_addr == 0 or starts_addr == 0 or \
            ends_addr == 0 or indents_addr == 0 or content_ends_addr == 0:
        return -1
    var source = BPtr(unsafe_from_address=source_addr)
    var starts = IPtr(unsafe_from_address=starts_addr)
    var ends = IPtr(unsafe_from_address=ends_addr)
    var indents = IPtr(unsafe_from_address=indents_addr)
    var content_ends = IPtr(unsafe_from_address=content_ends_addr)
    var line = 0
    var pos = 0
    starts[0] = Int64(0)
    while pos + BYTE_SIMD_WIDTH <= n:
        var chunk = source.load[width=BYTE_SIMD_WIDTH, alignment=1](pos)
        var newlines = chunk.eq(UInt8(10))
        if newlines.reduce_or():
            comptime for lane in range(BYTE_SIMD_WIDTH):
                if newlines[lane]:
                    var end = pos + lane
                    if end > Int(starts[line]) and source[end - 1] == UInt8(13):
                        end -= 1
                    ends[line] = Int64(end)
                    line += 1
                    if line >= capacity:
                        return -1
                    starts[line] = Int64(pos + lane + 1)
        pos += BYTE_SIMD_WIDTH
    while pos < n:
        if source[pos] == UInt8(10):
            var end = pos
            if end > Int(starts[line]) and source[end - 1] == UInt8(13):
                end -= 1
            ends[line] = Int64(end)
            line += 1
            if line >= capacity:
                return -1
            starts[line] = Int64(pos + 1)
        pos += 1
    if n == 0 or source[n - 1] != UInt8(10):
        ends[line] = Int64(n)
        line += 1
    else:
        starts[line] = Int64(n)
        ends[line] = Int64(n)
        line += 1

    for current in range(line):
        scan_line_metadata(
            source, starts, ends, indents, content_ends, current
        )
    return line


def quoted_size(source: BPtr, n: Int) -> Int:
    var size = 2
    for i in range(n):
        var c = source[i]
        if c == UInt8(34) or c == UInt8(92) or c == UInt8(8) or c == UInt8(9) or \
                c == UInt8(10) or c == UInt8(12) or c == UInt8(13):
            size += 2
        elif c < UInt8(32):
            size += 6
        else:
            size += 1
    return size


@export("mpy_quoted_size")
def mpy_quoted_size(source_addr: Int, n: Int) abi("C") -> Int:
    if source_addr == 0 or n < 0:
        return -1
    return quoted_size(BPtr(unsafe_from_address=source_addr), n)


def hex_digit(v: UInt8) -> UInt8:
    if v < UInt8(10):
        return UInt8(48) + v
    return UInt8(65) + (v - UInt8(10))


@export("mpy_quote")
def quote(
    source_addr: Int, n: Int, dest_addr: Int, capacity: Int
) abi("C") -> Int:
    if source_addr == 0 or dest_addr == 0 or n < 0 or capacity < 2:
        return -1
    var source = BPtr(unsafe_from_address=source_addr)
    var dest = BPtr(unsafe_from_address=dest_addr)
    var required = quoted_size(source, n)
    if required > capacity:
        return -1
    var j = 0
    dest[j] = UInt8(34)
    j += 1
    for i in range(n):
        var c = source[i]
        if c == UInt8(34):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(34)
            j += 2
        elif c == UInt8(92):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(92)
            j += 2
        elif c == UInt8(8):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(98)
            j += 2
        elif c == UInt8(9):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(116)
            j += 2
        elif c == UInt8(10):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(110)
            j += 2
        elif c == UInt8(12):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(102)
            j += 2
        elif c == UInt8(13):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(114)
            j += 2
        elif c < UInt8(32):
            dest[j] = UInt8(92)
            dest[j + 1] = UInt8(117)
            dest[j + 2] = UInt8(48)
            dest[j + 3] = UInt8(48)
            dest[j + 4] = hex_digit(c >> 4)
            dest[j + 5] = hex_digit(c & UInt8(15))
            j += 6
        else:
            dest[j] = c
            j += 1
    dest[j] = UInt8(34)
    return j + 1
