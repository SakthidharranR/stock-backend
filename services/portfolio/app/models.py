from typing import Literal

from pydantic import BaseModel, Field


class PortfolioChartPoint(BaseModel):
    time: int
    value: float


class PortfolioSummary(BaseModel):
    cash_balance: float
    equity: float
    total_value: float
    day_change: float
    day_change_percent: float
    chart_points: list[PortfolioChartPoint] = Field(default_factory=list)


class HoldingItem(BaseModel):
    symbol: str
    name: str
    shares: float
    avg_cost: float
    price: float
    change: float
    change_percent: float
    equity: float


class OrderRequest(BaseModel):
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float = Field(gt=0)


class OrderItem(BaseModel):
    id: str
    symbol: str
    side: str
    quantity: float
    fill_price: float
    total: float
    created_at: str


class OrderResponse(BaseModel):
    order: OrderItem
    cash_balance: float


class CashTransferRequest(BaseModel):
    side: Literal["deposit", "withdraw"]
    amount: float = Field(gt=0)


class CashTransferItem(BaseModel):
    id: str
    side: str
    amount: float
    created_at: str


class CashTransferResponse(BaseModel):
    transfer: CashTransferItem
    cash_balance: float
