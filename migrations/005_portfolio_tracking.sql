-- Portfolio value tracking (day P&L baseline + chart marks)

CREATE TABLE IF NOT EXISTS portfolio_daily_baseline (
  account_id    UUID NOT NULL REFERENCES accounts(id),
  baseline_date DATE NOT NULL,
  start_value   NUMERIC(18,2) NOT NULL,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, baseline_date)
);

CREATE TABLE IF NOT EXISTS portfolio_marks (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  account_id    UUID NOT NULL REFERENCES accounts(id),
  marked_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  total_value   NUMERIC(18,2) NOT NULL,
  cash_balance  NUMERIC(18,2) NOT NULL,
  equity        NUMERIC(18,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_marks_account_time
  ON portfolio_marks (account_id, marked_at DESC);
