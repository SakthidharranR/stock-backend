-- Cash deposits / withdrawals for buying power

CREATE TABLE IF NOT EXISTS cash_transfers (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id  UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
  side        TEXT NOT NULL CHECK (side IN ('deposit', 'withdraw')),
  amount      NUMERIC(18, 2) NOT NULL CHECK (amount > 0),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_cash_transfers_account_time
  ON cash_transfers (account_id, created_at ASC);
