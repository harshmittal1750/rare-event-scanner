from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AssetSpec:
    """One tracked asset: the symbol our system uses, the source, and the source's ticker."""

    def __init__(self, symbol: str, source: str, source_symbol: str, asset_class: str):
        self.symbol = symbol
        self.source = source
        self.source_symbol = source_symbol
        self.asset_class = asset_class


DEFAULT_ASSETS: list[AssetSpec] = [
    # Indices / stocks via yfinance
    AssetSpec("SPX", "yfinance", "^GSPC", "index"),
    AssetSpec("NDX", "yfinance", "^NDX", "index"),
    AssetSpec("DJI", "yfinance", "^DJI", "index"),
    AssetSpec("VIX", "yfinance", "^VIX", "index"),
    AssetSpec("GOLD", "yfinance", "GC=F", "commodity"),
    AssetSpec("OIL", "yfinance", "CL=F", "commodity"),
    AssetSpec("DXY", "yfinance", "DX-Y.NYB", "forex"),
    # Crypto spot via binance
    AssetSpec("BTC", "binance", "BTC/USDT", "crypto"),
    AssetSpec("ETH", "binance", "ETH/USDT", "crypto"),
    AssetSpec("SOL", "binance", "SOL/USDT", "crypto"),
    AssetSpec("BNB", "binance", "BNB/USDT", "crypto"),
    AssetSpec("XRP", "binance", "XRP/USDT", "crypto"),
    # Crypto perps via hyperliquid — prefix with HL- so rows don't collide with spot
    AssetSpec("HL-BTC", "hyperliquid", "BTC", "crypto_perp"),
    AssetSpec("HL-ETH", "hyperliquid", "ETH", "crypto_perp"),
    AssetSpec("HL-SOL", "hyperliquid", "SOL", "crypto_perp"),
    AssetSpec("HL-HYPE", "hyperliquid", "HYPE", "crypto_perp"),
    AssetSpec("HL-DOGE", "hyperliquid", "DOGE", "crypto_perp"),
    AssetSpec("HL-XRP", "hyperliquid", "XRP", "crypto_perp"),
    AssetSpec("HL-SUI", "hyperliquid", "SUI", "crypto_perp"),
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: Path = Field(default=Path("./data"))
    db_filename: str = Field(default="scanner.duckdb")

    publisher_url: str = Field(default="http://localhost:3000/api/rare-event")
    publisher_token: str = Field(default="dev-token")
    publisher_enabled: bool = Field(default=True)

    backfill_days: int = Field(default=365 * 10)
    scan_interval_minutes: int = Field(default=60)

    rarity_threshold: float = Field(
        default=99.0,
        description="Percentile (0-100). Events must be at/above this to be published.",
    )

    dry_run: bool = Field(default=False, description="If true, log events instead of publishing.")

    @property
    def db_path(self) -> Path:
        return self.data_dir / self.db_filename


settings = Settings()
