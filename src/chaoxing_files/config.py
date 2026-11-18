import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Settings:
    cookie_file: Path = field(
        default_factory=lambda: Path(
            os.environ.get(
                "CHAOXING_COOKIE_FILE", str(ROOT / ".chaoxing" / "cookies.json")
            )
        )
    )
    download_dir: Path = field(
        default_factory=lambda: Path(
            os.environ.get("CHAOXING_DOWNLOAD_DIR", str(ROOT / "downloads"))
        )
    )
    max_bytes: int = field(
        default_factory=lambda: (
            int(os.environ.get("CHAOXING_MAX_FILE_MB", "512")) * 1024 * 1024
        )
    )
    allowed_domains: tuple[str, ...] = field(
        default_factory=lambda: (
            "chaoxing.com",
            "chaoxing.com.cn",
            "d0.cldisk.com",
            *filter(
                None,
                (
                    s.strip().lower()
                    for s in os.environ.get("CHAOXING_EXTRA_DOMAINS", "").split(",")
                ),
            ),
        )
    )

    def __post_init__(self):
        if self.max_bytes <= 0:
            raise ValueError("CHAOXING_MAX_FILE_MB must be positive")
