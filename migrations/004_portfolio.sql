-- Paper trading portfolio tables

CREATE TABLE IF NOT EXISTS accounts (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL UNIQUE REFERENCES users(id),
  cash_balance  NUMERIC(18,2) NOT NULL DEFAULT 10000.00,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS holdings (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    UUID NOT NULL REFERENCES accounts(id),
  symbol        TEXT NOT NULL REFERENCES symbols(symbol),
  shares        NUMERIC(18,6) NOT NULL,
  avg_cost      NUMERIC(18,4) NOT NULL,
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (account_id, symbol)
);

CREATE TABLE IF NOT EXISTS orders (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    UUID NOT NULL REFERENCES accounts(id),
  symbol        TEXT NOT NULL REFERENCES symbols(symbol),
  side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
  quantity      NUMERIC(18,6) NOT NULL,
  fill_price    NUMERIC(18,4) NOT NULL,
  total         NUMERIC(18,2) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_orders_account ON orders (account_id, created_at DESC);
