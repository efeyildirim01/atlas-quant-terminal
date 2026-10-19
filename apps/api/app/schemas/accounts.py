from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.auth.security import MIN_PASSWORD_LENGTH


class Credentials(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        local, _, domain = v.partition("@")
        if not local or "." not in domain or " " in v:
            raise ValueError("invalid email address")
        return v


class RegisterIn(Credentials):
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)
    display_name: str | None = Field(None, max_length=120)


class PasswordChangeIn(BaseModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    user_id: str
    email: str
    display_name: str | None
    role: str
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


class PortfolioIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field("TRY", pattern="^[A-Z]{3}$")


class PortfolioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    portfolio_id: str
    name: str
    base_currency: str
    created_at: datetime


class TransactionIn(BaseModel):
    transaction_type: Literal["deposit", "withdrawal", "buy", "sell", "dividend", "fee"]
    transaction_date: date
    symbol: str | None = Field(None, max_length=32, description="Required for buy/sell; optional for dividends")
    quantity: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=8)
    price: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=8)
    commission: Decimal = Field(Decimal(0), ge=0, max_digits=24, decimal_places=8)
    amount: Decimal | None = Field(None, gt=0, max_digits=24, decimal_places=8)
    settlement_date: date | None = None

    @model_validator(mode="after")
    def _shape(self) -> "TransactionIn":
        if self.transaction_type in ("buy", "sell"):
            if not self.symbol or self.quantity is None or self.price is None:
                raise ValueError("buy/sell need symbol, quantity and price (prices are never inferred)")
            if self.amount is not None:
                raise ValueError("buy/sell take quantity and price, not amount")
        else:
            if self.amount is None:
                raise ValueError(f"{self.transaction_type} needs amount")
            if self.quantity is not None or self.price is not None:
                raise ValueError(f"{self.transaction_type} takes amount, not quantity/price")
        if self.settlement_date and self.settlement_date < self.transaction_date:
            raise ValueError("settlement_date cannot precede transaction_date")
        return self


class TransactionOut(BaseModel):
    transaction_id: int
    transaction_type: str
    transaction_date: date
    symbol: str | None
    quantity: float | None
    price: float | None
    commission: float
    amount: float | None
    settlement_date: date | None
