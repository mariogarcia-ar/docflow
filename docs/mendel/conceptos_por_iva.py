#!/usr/bin/env python3
"""
Dado un IVA, devuelve la columna con los valores de los conceptos de
`scripts/conceptos_por_iva.md`.

`scripts/conceptos_por_iva.md` contiene una tabla que, por cada cuenta contable, lista el código de
concepto según el IVA:

    |  |  | Concepto | 21% | 10,5% | 27% | 2,5% | Exento / No gravado |
    | CT001 | 4221,05 | Indumentaria personal | 164 | 79 | — | — | — |

Dado un IVA (por ejemplo `21`, `10,5`, `27`, `2,5`, `exento`), el script retorna un CSV
con los pares `concepto,codigo` de esa columna (codigo = código de concepto). Los `—`
se omiten (no hay concepto) y los valores tachados con `~~...~~` se descartan (conceptos
dados de baja); una celda puede tener varios códigos separados por coma (una fila por
código).

Uso:
  python3 scripts/conceptos_por_iva.py 21
  python3 scripts/conceptos_por_iva.py 10,5 > conceptos.csv
  python3 scripts/conceptos_por_iva.py exento --format json
  python3 scripts/conceptos_por_iva.py --list
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE = REPO / "scripts" / "conceptos_por_iva.md"

# Celdas sin concepto.
EMPTY = {"", "—", "-", "–"}

# Alias de cada columna de IVA -> nombre canónico interno.
IVA_ALIASES = {
    "21": "21%",
    "27": "27%",
    "10,5": "10,5%",
    "2,5": "2,5%",
    "exento": "Exento / No gravado",
    "no gravado": "Exento / No gravado",
    "exento / no gravado": "Exento / No gravado",
}


def normalize(value: str) -> str:
    """Normaliza un IVA o un encabezado: sin %, sin espacios, decimales con coma."""
    v = value.strip().lower().replace("%", "").replace(".", ",")
    v = re.sub(r"\s*/\s*", " / ", v)
    return re.sub(r"\s+", " ", v).strip()


def resolve_column(value: str) -> str:
    """Devuelve el nombre canónico de la columna para el IVA indicado."""
    key = normalize(value)
    if key in IVA_ALIASES:
        return IVA_ALIASES[key]
    raise SystemExit(
        f"ERROR: IVA desconocido: {value!r}. "
        f"Opciones: {', '.join(sorted(set(IVA_ALIASES.values())))}"
    )


def parse_values(cell: str) -> list[str]:
    """Extrae los códigos de una celda, descartando tachados (`~~...~~`) y vacíos.

    Los tachados son conceptos dados de baja: se eliminan antes de separar. Si queda
    algún marcador `~~` suelto (tachado mal formado), se descarta ese token.
    """
    clean = re.sub(r"~~.*?~~", "", cell)
    parts = [p.strip() for p in clean.split(",")]
    return [p for p in parts if p not in EMPTY and "~~" not in p]


def parse_table(source: Path) -> tuple[list[str], list[list[str]]]:
    """Devuelve (encabezados, filas de la tabla Markdown de conceptos)."""
    lines = [
        ln for ln in source.read_text(encoding="utf-8").splitlines()
        if ln.lstrip().startswith("|")
    ]
    if not lines:
        raise SystemExit(f"ERROR: no se encontró la tabla en {source}")

    def cells(line: str) -> list[str]:
        return [c.strip() for c in line.strip().strip("|").split("|")]

    header = cells(lines[0])
    rows = [cells(ln) for ln in lines[1:] if not set(cells(ln)[0]) <= set("-: ")]
    return header, rows


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("iva", nargs="?", help="IVA a consultar (ej. 21, 10,5, 27, exento)")
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help="Markdown con la tabla de conceptos (default: scripts/conceptos_por_iva.md)")
    ap.add_argument("--format", choices=["csv", "json"], default="csv",
                    help="Formato de salida (default: csv)")
    ap.add_argument("--out", type=Path, default=None,
                    help="Archivo de salida (default: stdout)")
    ap.add_argument("--list", action="store_true",
                    help="Lista los IVA disponibles y termina")
    args = ap.parse_args()

    header, rows = parse_table(args.source)
    columns = {}  # nombre canónico -> índice de columna
    for i, h in enumerate(header):
        key = normalize(h)
        if key in IVA_ALIASES:
            columns[IVA_ALIASES[key]] = i

    if args.list:
        for name, _ in sorted(columns.items(), key=lambda kv: kv[1]):
            print(name)
        return 0

    if not args.iva:
        ap.error("falta el IVA (o usá --list para ver las opciones)")
    column = resolve_column(args.iva)
    idx = columns[column]

    # Una fila por código: concepto (nombre) + codigo (código de concepto de esa alícuota).
    result = [
        {"concepto": row[2] if len(row) > 2 else "", "codigo": code}
        for row in rows if len(row) > idx
        for code in parse_values(row[idx])
    ]

    out = args.out.open("w", newline="", encoding="utf-8") if args.out else sys.stdout
    try:
        if args.format == "json":
            out.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
        else:
            w = csv.writer(out)
            w.writerow(["concepto", "codigo"])
            for r in result:
                w.writerow([r["concepto"], r["codigo"]])
    finally:
        if args.out:
            out.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
