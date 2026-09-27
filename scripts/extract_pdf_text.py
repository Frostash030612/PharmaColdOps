"""Minimal dependency-free PDF text extractor (FlateDecode streams + Tj/TJ operators).

Usage: python extract_pdf_text.py <input.pdf> [output.txt]
"""
import re
import sys
import zlib

OBJ_RE = re.compile(rb"(\d+)\s+(\d+)\s+obj(.*?)endobj", re.S)
STREAM_RE = re.compile(rb"stream\r?\n(.*?)\r?\nendstream", re.S)


def decode_stream(data: bytes, obj: bytes) -> bytes | None:
    if b"FlateDecode" in obj:
        try:
            return zlib.decompress(data)
        except Exception:
            try:
                return zlib.decompressobj().decompress(data)
            except Exception:
                return None
    return data if b"Tj" in data or b"TJ" in data else None


def unescape(s: bytes) -> str:
    out = []
    i = 0
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\":
            nxt = s[i + 1:i + 2]
            mapping = {b"n": "\n", b"r": "\r", b"t": "\t", b"b": "\b",
                       b"f": "\f", b"(": "(", b")": ")", b"\\": "\\"}
            if nxt in mapping:
                out.append(mapping[nxt])
                i += 2
                continue
            if nxt.isdigit():
                m = re.match(rb"[0-7]{1,3}", s[i + 1:])
                if m:
                    out.append(chr(int(m.group(0), 8)))
                    i += 1 + len(m.group(0))
                    continue
            i += 2
            continue
        out.append(c.decode("latin-1"))
        i += 1
    return "".join(out)


def extract_text_from_content(content: bytes) -> str:
    pieces = []
    # Literal strings used by Tj / TJ / ' / "
    for m in re.finditer(rb"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)", content, re.S):
        pieces.append(("str", m.start(), unescape(m.group(0)[1:-1])))
    # Track text-positioning operators to insert newlines roughly
    for m in re.finditer(rb"(Td|TD|T\*|ET|BT)", content):
        pieces.append(("op", m.start(), m.group(0).decode()))
    pieces.sort(key=lambda p: p[1])
    out = []
    for kind, _, val in pieces:
        if kind == "op":
            if val in ("Td", "TD", "T*", "ET"):
                out.append("\n")
        else:
            out.append(val)
    text = "".join(out)
    text = re.sub(r"\n{2,}", "\n", text)
    return text


def main() -> int:
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else None
    raw = open(src, "rb").read()
    pages = []
    for m in OBJ_RE.finditer(raw):
        obj = m.group(3)
        if b"/Image" in obj or b"/Font" in obj:
            continue
        sm = STREAM_RE.search(obj)
        if not sm:
            continue
        data = decode_stream(sm.group(1), obj)
        if not data or (b"Tj" not in data and b"TJ" not in data):
            continue
        txt = extract_text_from_content(data)
        if txt.strip():
            pages.append(txt)
    result = ("\n\n===== PAGE BREAK =====\n\n").join(pages)
    if dst:
        with open(dst, "w", encoding="utf-8") as fh:
            fh.write(result)
        print(f"pages_with_text={len(pages)} chars={len(result)} -> {dst}")
    else:
        sys.stdout.reconfigure(encoding="utf-8")
        print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
