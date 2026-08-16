from pydantic import BaseModel


class SymbolResult(BaseModel):
    symbol: str
    name: str
    exchange: str = "US"


class QuoteResult(BaseModel):
    symbol: str
    name: str | None = None
    price: float
    change: float
    change_percent: float
    prev_close: float | None = None


class CandlePoint(BaseModel):
    time: int
    close: float


class CandlesResponse(BaseModel):
    symbol: str
    range: str
    resolution: str
    points: list[CandlePoint]


class NewsItem(BaseModel):
    id: str
    headline: str
    source: str | None = None
    url: str | None = None
    published_at: str | None = None


class SuggestionItem(BaseModel):
    symbol: str
    name: str
    label: str | None = None
    price: float
    change: float
    change_percent: float
