"""QRコード画像(シート)群からファイルを復元するツール。

file_to_qr.py で生成したQRコード画像(1枚に複数コードがまとまったシート画像でも可)
を読み取り、元のファイルを復元する。

処理の流れ:
    1. 指定されたパス以下の画像ファイル(png/jpg/jpeg/bmp/gif/tif)を走査し、
       含まれる全QRコードを読み取る。
    2. ヘッダー情報(ファイルID / 連番 / 総数)をもとにファイルIDごとにチャンクを
       グループ化し、欠けているチャンクがないか確認する。
    3. 連番0のチャンクからメタ情報(元ファイル名・圧縮方式・SHA-256)を取得し、
       残りのチャンクを結合・伸長したうえでSHA-256を検証してから保存する。
    4. 複数ファイル分のQRコードが混在していても、ファイルIDごとに自動で
       振り分けて復元する。

使い方:
    python qr_to_file.py <QRコード画像またはディレクトリ...> [-o 出力ディレクトリ]

例:
    python qr_to_file.py qr_out -o restored
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import lzma
import struct
import sys
import zlib
from pathlib import Path

from PIL import Image
from pyzbar.pyzbar import ZBarSymbol
from pyzbar.pyzbar import decode as zbar_decode

MAGIC = b"QRF1"
HEADER = struct.Struct(">4s8sII")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}

LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]

# file_to_qr.py と同じBase45実装(QRコードは英数字モードのASCII文字列として格納されている)
BASE45_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"
BASE45_LOOKUP = {c: i for i, c in enumerate(BASE45_CHARSET)}


def base45_decode(s: str) -> bytes:
    out = bytearray()
    n = len(s)
    for i in range(0, n - n % 3, 3):
        x = BASE45_LOOKUP[s[i]] + BASE45_LOOKUP[s[i + 1]] * 45 + BASE45_LOOKUP[s[i + 2]] * 45 * 45
        out.append(x // 256)
        out.append(x % 256)
    rem = n % 3
    if rem == 2:
        x = BASE45_LOOKUP[s[-2]] + BASE45_LOOKUP[s[-1]] * 45
        out.append(x)
    elif rem == 1:
        raise ValueError("Base45文字列の長さが不正です")
    return bytes(out)


def decompress(data: bytes, algo: str) -> bytes:
    if algo == "none":
        return data
    if algo == "lzma_raw":
        return lzma.decompress(data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS)
    if algo == "zlib_raw":
        return zlib.decompressobj(-15).decompress(data)
    if algo == "bz2":
        return bz2.decompress(data)
    raise ValueError(f"未知の圧縮方式です: {algo}")


def collect_image_paths(inputs: list[str]) -> list[Path]:
    paths: list[Path] = []
    for raw in inputs:
        p = Path(raw)
        if p.is_dir():
            paths.extend(sorted(f for f in p.rglob("*") if f.suffix.lower() in IMAGE_EXTS))
        elif p.is_file():
            paths.append(p)
        else:
            print(f"警告: パスが見つかりません: {p}", file=sys.stderr)
    return paths


def safe_filename(name: str) -> str:
    """QRコードに埋め込まれたファイル名からパストラバーサル等の危険な要素を除去する。"""
    candidate = Path(name).name  # ディレクトリ部分を除去
    candidate = candidate.strip().lstrip(".")
    if not candidate:
        candidate = "recovered_file"
    return candidate


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    n = 1
    while True:
        candidate = path.with_name(f"{stem} ({n}){suffix}")
        if not candidate.exists():
            return candidate
        n += 1


def main() -> None:
    parser = argparse.ArgumentParser(description="QRコード画像群からファイルを復元します。")
    parser.add_argument("inputs", nargs="+", help="QRコード画像ファイル、またはそれらを含むディレクトリ")
    parser.add_argument("-o", "--output", default="restored", help="復元したファイルの出力先ディレクトリ (既定: restored)")
    args = parser.parse_args()

    image_paths = collect_image_paths(args.inputs)
    if not image_paths:
        print("エラー: 画像ファイルが見つかりませんでした。", file=sys.stderr)
        sys.exit(1)

    # file_id -> {index: payload_bytes}
    files: dict[bytes, dict[int, bytes]] = {}
    totals: dict[bytes, int] = {}

    scanned_codes = 0
    for path in image_paths:
        try:
            image = Image.open(path)
        except Exception as exc:
            print(f"警告: 画像を開けませんでした ({path}): {exc}", file=sys.stderr)
            continue

        for symbol in zbar_decode(image, symbols=[ZBarSymbol.QRCODE]):
            try:
                text = symbol.data.decode("ascii")
                raw = base45_decode(text)
            except (UnicodeDecodeError, ValueError, KeyError):
                continue  # このツールで生成したQRコードではない
            if len(raw) < HEADER.size or raw[:4] != MAGIC:
                continue  # このツールで生成したQRコードではない
            magic, file_id, index, total = HEADER.unpack(raw[:HEADER.size])
            payload = raw[HEADER.size:]
            files.setdefault(file_id, {})[index] = payload
            totals[file_id] = total
            scanned_codes += 1

    if not files:
        print("エラー: 対象のQRコードが1つも見つかりませんでした。", file=sys.stderr)
        sys.exit(1)

    print(f"読み取ったQRコード数: {scanned_codes} / 検出ファイル数: {len(files)}")

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    exit_code = 0
    for file_id, chunks in files.items():
        total = totals[file_id]
        missing = [i for i in range(total) if i not in chunks]
        short_id = file_id.hex()
        if missing:
            print(f"エラー [{short_id}]: チャンクが不足しています (欠損連番: {missing})", file=sys.stderr)
            exit_code = 1
            continue

        try:
            metadata = json.loads(chunks[0].decode("utf-8"))
            compressed_data = b"".join(chunks[i] for i in range(1, total))
            data = decompress(compressed_data, metadata["algo"])

            if hashlib.sha256(data).hexdigest() != metadata["sha256"]:
                print(f"エラー [{short_id}]: SHA-256が一致しません。データが破損している可能性があります。", file=sys.stderr)
                exit_code = 1
                continue

            out_path = unique_path(output_dir / safe_filename(metadata["filename"]))
            out_path.write_bytes(data)
            print(f"復元完了: {out_path} ({len(data):,} bytes)")
        except Exception as exc:
            print(f"エラー [{short_id}]: 復元に失敗しました: {exc}", file=sys.stderr)
            exit_code = 1

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
