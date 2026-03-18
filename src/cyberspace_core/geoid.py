from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

DEFAULT_GEOID_MODEL = "egm2008-2_5"
SUPPORTED_GEOID_MODELS = ("egm2008-2_5", "egm2008-1")


class GeoidError(RuntimeError):
    pass


class GeoidModelNotFoundError(GeoidError):
    pass


class GeoidFormatError(GeoidError):
    pass


def normalize_geoid_model(model: str) -> str:
    m = (model or "").strip().lower()
    if m not in SUPPORTED_GEOID_MODELS:
        allowed = ", ".join(SUPPORTED_GEOID_MODELS)
        raise ValueError(f"unsupported geoid model '{model}' (allowed: {allowed})")
    return m


def _split_path_env(v: str) -> Iterable[Path]:
    for part in (v or "").split(os.pathsep):
        p = part.strip()
        if p:
            yield Path(p).expanduser()


def default_geoid_search_dirs() -> List[Path]:
    dirs: List[Path] = []

    csp = os.environ.get("CYBERSPACE_GEOID_PATH", "")
    dirs.extend(_split_path_env(csp))

    glp = os.environ.get("GEOGRAPHICLIB_GEOID_PATH", "")
    dirs.extend(_split_path_env(glp))

    gld = os.environ.get("GEOGRAPHICLIB_DATA", "").strip()
    if gld:
        dirs.append(Path(gld).expanduser() / "geoids")

    csh = os.environ.get("CYBERSPACE_HOME", "").strip()
    if csh:
        dirs.append(Path(csh).expanduser() / "geoids")
    else:
        dirs.append(Path.home() / ".cyberspace" / "geoids")

    dirs.extend(
        [
            Path("/usr/share/GeographicLib/geoids"),
            Path("/usr/local/share/GeographicLib/geoids"),
            Path("/opt/homebrew/share/GeographicLib/geoids"),
        ]
    )

    out: List[Path] = []
    seen: set[str] = set()
    for d in dirs:
        k = str(d)
        if k in seen:
            continue
        seen.add(k)
        out.append(d)
    return out


def candidate_model_paths(model: str, *, geoid_dir: Optional[Path] = None) -> List[Path]:
    m = normalize_geoid_model(model)
    if geoid_dir is not None:
        return [Path(geoid_dir) / f"{m}.pgm"]
    return [d / f"{m}.pgm" for d in default_geoid_search_dirs()]


def find_geoid_model_path(model: str, *, geoid_dir: Optional[Path] = None) -> Path:
    candidates = candidate_model_paths(model, geoid_dir=geoid_dir)
    for p in candidates:
        if p.is_file():
            return p
    joined = "\n".join(str(p) for p in candidates)
    raise GeoidModelNotFoundError(
        f"geoid dataset '{normalize_geoid_model(model)}.pgm' was not found.\n"
        f"Searched:\n{joined}"
    )


@dataclass(frozen=True)
class GeoidGrid:
    model: str
    path: Path
    width: int
    height: int
    maxval: int
    data_offset: int
    scale: float
    offset: float

    @property
    def row_bytes(self) -> int:
        return self.width * 2


def _read_token_and_comments(fp) -> Tuple[List[str], List[str]]:
    tokens: List[str] = []
    comments: List[str] = []
    token = bytearray()
    in_comment = False

    while len(tokens) < 4:
        b = fp.read(1)
        if not b:
            break

        if in_comment:
            if b == b"\n":
                in_comment = False
            continue

        if b == b"#":
            if token:
                tokens.append(token.decode("ascii"))
                token.clear()
            in_comment = True
            line = fp.readline().decode("ascii", errors="replace").strip()
            comments.append(line)
            in_comment = False
            continue

        if b.isspace():
            if token:
                tokens.append(token.decode("ascii"))
                token.clear()
                if len(tokens) == 4:
                    break
            continue

        token.extend(b)

    if token and len(tokens) < 4:
        tokens.append(token.decode("ascii"))

    return tokens, comments


def _parse_scale_offset(comments: List[str]) -> Tuple[float, float]:
    scale: Optional[float] = None
    offset: Optional[float] = None

    for raw in comments:
        line = raw.strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0].lower()
        val = parts[1]
        if key == "scale":
            try:
                scale = float(val)
            except ValueError:
                pass
        elif key == "offset":
            try:
                offset = float(val)
            except ValueError:
                pass

    if scale is None or offset is None:
        raise GeoidFormatError("geoid PGM header is missing required Scale/Offset comments")
    return scale, offset


def load_geoid_grid(model: str, *, geoid_dir: Optional[Path] = None) -> GeoidGrid:
    model_n = normalize_geoid_model(model)
    path = find_geoid_model_path(model_n, geoid_dir=geoid_dir)

    with path.open("rb") as fp:
        tokens, comments = _read_token_and_comments(fp)
        if len(tokens) < 4:
            raise GeoidFormatError(f"invalid geoid PGM header: {path}")

        magic = tokens[0]
        if magic != "P5":
            raise GeoidFormatError(f"unsupported geoid file format '{magic}' in {path} (expected P5)")

        try:
            width = int(tokens[1], 10)
            height = int(tokens[2], 10)
            maxval = int(tokens[3], 10)
        except ValueError as e:
            raise GeoidFormatError(f"invalid width/height/maxval in geoid header for {path}") from e

        if width <= 1 or height <= 1:
            raise GeoidFormatError(f"invalid geoid grid dimensions in {path}: {width}x{height}")
        if maxval <= 0 or maxval > 65535:
            raise GeoidFormatError(f"invalid geoid maxval in {path}: {maxval}")

        scale, offset = _parse_scale_offset(comments)
        data_offset = fp.tell()

    return GeoidGrid(
        model=model_n,
        path=path,
        width=width,
        height=height,
        maxval=maxval,
        data_offset=data_offset,
        scale=scale,
        offset=offset,
    )


def _read_sample_u16be(fp, grid: GeoidGrid, row: int, col: int) -> int:
    pos = grid.data_offset + ((row * grid.width + col) * 2)
    fp.seek(pos)
    raw = fp.read(2)
    if len(raw) != 2:
        raise GeoidFormatError(f"unexpected EOF while reading geoid data from {grid.path}")
    return int.from_bytes(raw, "big", signed=False)


def _clamp_lat(lat_deg: float) -> float:
    if lat_deg < -90.0:
        return -90.0
    if lat_deg > 90.0:
        return 90.0
    return lat_deg


def _wrap_lon_360(lon_deg: float) -> float:
    lon = math.fmod(lon_deg, 360.0)
    if lon < 0.0:
        lon += 360.0
    if lon >= 360.0:
        lon -= 360.0
    return lon


_GRID_CACHE: Dict[Tuple[str, str], GeoidGrid] = {}


def get_cached_geoid_grid(model: str, *, geoid_dir: Optional[Path] = None) -> GeoidGrid:
    model_n = normalize_geoid_model(model)
    key = (model_n, str(geoid_dir) if geoid_dir is not None else "")
    g = _GRID_CACHE.get(key)
    if g is None:
        g = load_geoid_grid(model_n, geoid_dir=geoid_dir)
        _GRID_CACHE[key] = g
    return g


def geoid_undulation_m(
    lat_deg: float,
    lon_deg: float,
    *,
    model: str = DEFAULT_GEOID_MODEL,
    geoid_dir: Optional[Path] = None,
) -> float:
    grid = get_cached_geoid_grid(model, geoid_dir=geoid_dir)

    lat = _clamp_lat(float(lat_deg))
    lon = _wrap_lon_360(float(lon_deg))

    # GeographicLib gridded geoid conventions:
    # - row 0 = +90 deg latitude
    # - column 0 = 0 deg longitude
    # - lat spacing = 180 / (h - 1), lon spacing = 360 / w
    lat_step = 180.0 / float(grid.height - 1)
    lon_step = 360.0 / float(grid.width)

    row_f = (90.0 - lat) / lat_step
    col_f = lon / lon_step

    if row_f <= 0.0:
        r0 = 0
        fy = 0.0
    elif row_f >= float(grid.height - 1):
        r0 = grid.height - 2
        fy = 1.0
    else:
        r0 = int(math.floor(row_f))
        fy = row_f - float(r0)
    r1 = r0 + 1

    c0 = int(math.floor(col_f)) % grid.width
    fx = col_f - math.floor(col_f)
    c1 = (c0 + 1) % grid.width

    with grid.path.open("rb") as fp:
        v00 = _read_sample_u16be(fp, grid, r0, c0)
        v01 = _read_sample_u16be(fp, grid, r0, c1)
        v10 = _read_sample_u16be(fp, grid, r1, c0)
        v11 = _read_sample_u16be(fp, grid, r1, c1)

    top = (1.0 - fx) * float(v00) + fx * float(v01)
    bottom = (1.0 - fx) * float(v10) + fx * float(v11)
    pix = (1.0 - fy) * top + fy * bottom
    return grid.offset + (grid.scale * pix)
