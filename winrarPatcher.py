import re
import sys
from pathlib import Path

PATCHES = [
    (
        "CC CC CC 88 0D ?? ?? ?? ?? C3 CC ?? 89 ?? ?? 08 ?? 89 ?? ?? 10 ?? 89 ?? ?? 18",
        "CC CC CC C6 05 (??-1) ?? ?? ?? 01 C3 ?? 89 ?? ?? 08 ?? 89 ?? ?? 10 ?? 89 ?? ?? 18",
    )
]

EXPR_RE = re.compile(r"^\(\?\?([+-])(\d+)\)$")


def parse_pattern(pattern_str):
    """
    Returns a list of tokens, one per byte position:
      ("byte", value)      - fixed byte, must match / will be written
      ("wild", None)       - wildcard: matches anything, left untouched on write
      ("expr", (op, val))  - on write: take the byte that was at this exact
                              position in the ORIGINAL data and apply op/val
                              (e.g. ("-", 1) => original_byte - 1, mod 256)
    """
    tokens = []
    for t in pattern_str.split():
        if t == "??":
            tokens.append(("wild", None))
            continue

        m = EXPR_RE.match(t)
        if m:
            op, val = m.group(1), int(m.group(2))
            tokens.append(("expr", (op, val)))
            continue

        tokens.append(("byte", int(t, 16)))

    return tokens


def build_matcher(tokens):
    """Build fixed-byte array + mask used for searching, from search tokens."""
    search_bytes = bytes(v if t == "byte" else 0 for t, v in tokens)
    search_mask = [t == "byte" for t, _ in tokens]
    return search_bytes, search_mask


def find_matches(data, search_bytes, search_mask):
    pat_len = len(search_bytes)
    positions = []

    for i in range(len(data) - pat_len + 1):
        matched = True
        for j in range(pat_len):
            if search_mask[j] and data[i + j] != search_bytes[j]:
                matched = False
                break
        if matched:
            positions.append(i)

    return positions


def apply_expr(op, val, original_byte):
    if op == "+":
        return (original_byte + val) & 0xFF
    else:  # "-"
        return (original_byte - val) & 0xFF


def apply_patch(data, search_tokens, replace_tokens):
    if len(search_tokens) != len(replace_tokens):
        raise ValueError("search/replace token length mismatch")

    search_bytes, search_mask = build_matcher(search_tokens)
    pat_len = len(search_bytes)

    data = bytearray(data)
    positions = find_matches(data, search_bytes, search_mask)

    for i in positions:
        # snapshot original bytes of this match BEFORE writing anything,
        # so expr tokens always reference the pristine matched data
        original_slice = bytes(data[i:i + pat_len])

        for j in range(pat_len):
            rtype, rval = replace_tokens[j]
            if rtype == "byte":
                data[i + j] = rval
            elif rtype == "expr":
                op, val = rval
                data[i + j] = apply_expr(op, val, original_slice[j])
            # "wild" -> leave byte unchanged

    return bytes(data), len(positions)


def scan_pattern(data, search_tokens):
    search_bytes, search_mask = build_matcher(search_tokens)
    return len(find_matches(data, search_bytes, search_mask))


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <file.exe> [--dry-run] [--overwrite]")
        sys.exit(1)

    exe_path = Path(sys.argv[1])
    dry_run = "--dry-run" in sys.argv
    overwrite = "--overwrite" in sys.argv or "-o" in sys.argv

    if not exe_path.exists():
        print("File not found.")
        sys.exit(1)

    print(f"Source EXE: {exe_path}")

    data = exe_path.read_bytes()
    total_matches = 0

    print("Dry-run mode ON\n" if dry_run else "")

    for idx, (search, replace) in enumerate(PATCHES, 1):
        search_tokens = parse_pattern(search)
        replace_tokens = parse_pattern(replace)

        if len(search_tokens) != len(replace_tokens):
            print(f"[!] Patch {idx}: search/replace length mismatch")
            continue

        if dry_run:
            count = scan_pattern(data, search_tokens)
            print(f"[=] Patch {idx}: would apply {count} time(s)")
        else:
            data, count = apply_patch(data, search_tokens, replace_tokens)
            print(f"[+] Patch {idx}: applied {count} time(s)")

        total_matches += count

    if dry_run:
        if not overwrite:
            path = exe_path.with_suffix(".xex")
            print(f"Destination EXE: {path}")
        else:
            print(f"Destination EXE: {exe_path}")
        print(f"✔  Dry-run complete. Total matches found: {total_matches}")
        print("✔  No files were modified.")
        return

    if total_matches > 0:
        print(f"\n✔  Done. Total patches applied: {total_matches}")
        if overwrite:
            exe_path.write_bytes(data)
            print(f"Patched EXE: {exe_path}")
        else:
            path = exe_path.with_suffix(".xex")
            path.write_bytes(data)
            print(f"Patched EXE: {path}")
    else:
        print("\n✖  No patterns matched. File not modified.")


if __name__ == "__main__":
    main()