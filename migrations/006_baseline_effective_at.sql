-- 1D chart can start at first purchase time instead of midnight UTC
ALTER TABLE portfolio_daily_baseline
  ADD COLUMN IF NOT EXISTS effective_at TIMESTAMPTZ;
