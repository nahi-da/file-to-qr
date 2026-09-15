"""ファイルを圧縮してQRコード画像列に変換するツール。

処理の流れ:
    1. 入力ファイルを読み込み、複数の圧縮方式(LZMA/zlib/bz2/無圧縮)を試して
       最も小さくなるものを採用する。
    2. 圧縮後データを、QRコード1枚に収まる最大サイズのチャンクに分割する。
       (既定: バージョン40・誤り訂正レベルLで約2900バイト/枚)
    3. 各チャンクに「マジックナンバー / ファイルID / 連番 / 総数」からなる
       20バイトのヘッダーを付与し、QRコード画像として生成する。
       (先頭のチャンク(連番0)には元ファイル名やハッシュ値などのメタ情報を格納する)
    4. QRコードは指定枚数ごとに1枚のシート画像へグリッド状にまとめて保存し、
       生成される画像ファイル数を抑える。

使い方:
    python file_to_qr.py <入力ファイル> [-o 出力ディレクトリ] [--ec {L,M,Q,H}]
                          [--version 1-40] [--box-size N] [--border N]
                          [--cols N] [--rows N]

例:
    python file_to_qr.py sample.py
    python file_to_qr.py sample.py -o qr_out --ec M --cols 4 --rows 4
"""
from __future__ import annotations

import argparse
import bz2
import hashlib
import json
import lzma
import os
import struct
import sys
import zlib
from pathlib import Path

import qrcode
from qrcode.constants import (
    ERROR_CORRECT_H,
    ERROR_CORRECT_L,
    ERROR_CORRECT_M,
    ERROR_CORRECT_Q,
)
from PIL import Image, ImageDraw, ImageFont

MAGIC = b"QRF1"
# magic(4s) + file_id(8s) + index(I) + total(I) = 20 bytes
HEADER = struct.Struct(">4s8sII")

# QRコードの英数字モード(5.5bit/文字)にそのまま収まる文字集合を使う独自Base45実装。
# zbar は QR のバイトモードのデータを Latin-1 -> UTF-8 として扱うため、
# 0x80 以上のバイトを含む生バイナリをバイトモードで格納すると壊れる。
# そのため実際にQRへ格納する文字列は必ずBase45(ASCII文字のみ)に変換する。
BASE45_CHARSET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ $%*+-./:"


def base45_encode(data: bytes) -> str:
    out = []
    n = len(data)
    for i in range(0, n - n % 2, 2):
        x = data[i] * 256 + data[i + 1]
        c = x % 45
        x //= 45
        d = x % 45
        e = x // 45
        out.append(BASE45_CHARSET[c])
        out.append(BASE45_CHARSET[d])
        out.append(BASE45_CHARSET[e])
    if n % 2:
        x = data[-1]
        c = x % 45
        d = x // 45
        out.append(BASE45_CHARSET[c])
        out.append(BASE45_CHARSET[d])
    return "".join(out)

EC_MAP = {
    "L": ERROR_CORRECT_L,
    "M": ERROR_CORRECT_M,
    "Q": ERROR_CORRECT_Q,
    "H": ERROR_CORRECT_H,
}

# データを直接RAW形式で圧縮し、コンテナのヘッダー/フッター分のオーバーヘッドを削減する
LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 9 | lzma.PRESET_EXTREME}]


def compress_best(data: bytes) -> tuple[bytes, str]:
    """複数の圧縮方式を試し、最も小さくなる (圧縮後データ, 方式名) を返す。"""
    candidates: dict[str, bytes] = {"none": data}

    try:
        candidates["lzma_raw"] = lzma.compress(
            data, format=lzma.FORMAT_RAW, filters=LZMA_FILTERS
        )
    except Exception:
        pass

    try:
        co = zlib.compressobj(9, zlib.DEFLATED, -15)
        candidates["zlib_raw"] = co.compress(data) + co.flush()
    except Exception:
        pass

    try:
        candidates["bz2"] = bz2.compress(data, 9)
    except Exception:
        pass

    algo = min(candidates, key=lambda k: len(candidates[k]))
    return candidates[algo], algo


def calibrate_max_payload(version: int, ec: int) -> int:
    """指定バージョン/誤り訂正レベルでQRコード1枚に収まる最大バイト数(Base45変換前)を
    二分探索で求める。

    ダミーデータには乱数を用いる(全ゼロ等の偏ったデータでは、内部のReed-Solomon
    実装がまれに例外を送出する既知の境界ケースがあるため)。
    """
    lo, hi, best = 1, 3200, 1
    while lo <= hi:
        mid = (lo + hi) // 2
        qr = qrcode.QRCode(version=version, error_correction=ec)
        qr.add_data(base45_encode(os.urandom(mid)))
        try:
            qr.make(fit=False)
            best = mid
            lo = mid + 1
        except Exception:
            hi = mid - 1
    return best


def make_qr_image(payload: bytes, version: int, ec: int, box_size: int, border: int) -> Image.Image:
    """payload(生バイト列)をBase45文字列に変換したうえでQRコード画像化する。

    まれに特定のバイト列でエンコードが失敗する既知の境界ケースがあるため、
    その場合はバージョンを上げて再試行する(デコード側はバージョン混在でも
    問題なく読み取れる)。
    """
    encoded = base45_encode(payload)
    ec_candidates = [ec] + [e for e in (ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H) if e != ec]
    last_error: Exception | None = None
    for v in range(version, 41):
        for e in ec_candidates:
            try:
                qr = qrcode.QRCode(version=v, error_correction=e, box_size=box_size, border=border)
                qr.add_data(encoded)
                qr.make(fit=False)
                return qr.make_image(fill_color="black", back_color="white").get_image()
            except Exception as exc:  # pragma: no cover - 既知のまれな境界ケース対策
                last_error = exc
                continue
    raise RuntimeError(f"QRコードの生成に失敗しました: {last_error}")


def build_sheets(images: list[tuple[Image.Image, str]], cols: int, rows: int, output_dir: Path) -> int:
    """QRコード画像をグリッド状にまとめたシート画像を保存する。戻り値は保存枚数。"""
    per_sheet = max(1, cols * rows)
    gap = 12
    caption_h = 18
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None

    sheet_count = 0
    for start in range(0, len(images), per_sheet):
        batch = images[start:start + per_sheet]
        cell_w = max(img.width for img, _ in batch)
        cell_h = max(img.height for img, _ in batch) + caption_h

        sheet_w = cols * cell_w + (cols + 1) * gap
        sheet_h = rows * cell_h + (rows + 1) * gap
        sheet = Image.new("RGB", (sheet_w, sheet_h), "white")
        draw = ImageDraw.Draw(sheet)

        for i, (img, caption) in enumerate(batch):
            col = i % cols
            row = i // cols
            x = gap + col * (cell_w + gap)
            y = gap + row * (cell_h + gap)
            sheet.paste(img, (x, y))
            if font is not None:
                draw.text((x, y + img.height + 2), caption, fill="black", font=font)

        sheet_count += 1
        sheet.save(output_dir / f"qr_sheet_{sheet_count:03d}.png")

    return sheet_count


def main() -> None:
    parser = argparse.ArgumentParser(description="ファイルを圧縮してQRコード画像列に変換します。")
    parser.add_argument("input", help="変換する入力ファイル")
    parser.add_argument("-o", "--output", help="出力ディレクトリ (既定: <入力ファイル名>_qr)")
    parser.add_argument("--ec", choices=list(EC_MAP), default="L", help="誤り訂正レベル (既定: L=最大容量)")
    parser.add_argument("--version", type=int, default=40, help="QRコードバージョン 1-40 (既定: 40=最大容量)")
    parser.add_argument("--box-size", type=int, default=6, help="QRコード1モジュールのピクセルサイズ (既定: 6)")
    parser.add_argument("--border", type=int, default=4, help="QRコード周囲の余白モジュール数 (既定: 4)")
    parser.add_argument("--cols", type=int, default=3, help="1シートあたりの列数 (既定: 3)")
    parser.add_argument("--rows", type=int, default=3, help="1シートあたりの行数 (既定: 3)")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_file():
        print(f"エラー: 入力ファイルが見つかりません: {input_path}", file=sys.stderr)
        sys.exit(1)

    if not (1 <= args.version <= 40):
        print("エラー: --version は 1〜40 で指定してください。", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output) if args.output else input_path.with_name(input_path.stem + "_qr")
    output_dir.mkdir(parents=True, exist_ok=True)

    ec = EC_MAP[args.ec]
    original_data = input_path.read_bytes()
    compressed_data, algo = compress_best(original_data)
    sha256_hex = hashlib.sha256(original_data).hexdigest()
    file_id = hashlib.sha256(original_data).digest()[:8]

    metadata = {
        "filename": input_path.name,
        "size": len(original_data),
        "compressed_size": len(compressed_data),
        "algo": algo,
        "sha256": sha256_hex,
    }
    metadata_bytes = json.dumps(metadata, ensure_ascii=False).encode("utf-8")

    max_payload = calibrate_max_payload(args.version, ec)
    max_data_payload = max_payload - HEADER.size
    if max_data_payload <= 0:
        print("エラー: 指定されたバージョン/誤り訂正レベルではヘッダーすら格納できません。", file=sys.stderr)
        sys.exit(1)
    if len(metadata_bytes) > max_data_payload:
        print("エラー: ファイル名が長すぎてメタ情報がQRコード1枚に収まりません。", file=sys.stderr)
        sys.exit(1)

    data_chunks = [
        compressed_data[i:i + max_data_payload]
        for i in range(0, len(compressed_data), max_data_payload)
    ] or [b""]
    total_chunks = 1 + len(data_chunks)

    images: list[tuple[Image.Image, str]] = []

    header = HEADER.pack(MAGIC, file_id, 0, total_chunks)
    images.append((
        make_qr_image(header + metadata_bytes, args.version, ec, args.box_size, args.border),
        f"META 0/{total_chunks - 1}",
    ))

    for idx, chunk in enumerate(data_chunks, start=1):
        header = HEADER.pack(MAGIC, file_id, idx, total_chunks)
        img = make_qr_image(header + chunk, args.version, ec, args.box_size, args.border)
        images.append((img, f"{idx}/{total_chunks - 1}"))
        print(f"QRコード生成中... {idx}/{len(data_chunks)}", end="\r")

    print()
    sheet_count = build_sheets(images, args.cols, args.rows, output_dir)

    ratio = (1 - len(compressed_data) / len(original_data)) * 100 if original_data else 0.0
    print("--- 完了 ---")
    print(f"元ファイルサイズ: {len(original_data):,} bytes")
    print(f"圧縮後サイズ   : {len(compressed_data):,} bytes ({algo}, 圧縮率 {ratio:.1f}%)")
    print(f"QRコード枚数   : {total_chunks} (メタ情報1枚 + データ{len(data_chunks)}枚)")
    print(f"シート画像枚数 : {sheet_count}")
    print(f"出力先         : {output_dir}")


if __name__ == "__main__":
    main()
