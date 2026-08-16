-- Market reference tables (Finnhub symbol universe)

CREATE TABLE IF NOT EXISTS exchanges (
  code        TEXT PRIMARY KEY,
  name        TEXT NOT NULL
);

INSERT INTO exchanges (code, name) VALUES ('US', 'US Equities')
ON CONFLICT (code) DO NOTHING;

CREATE TABLE IF NOT EXISTS symbols (
  symbol      TEXT PRIMARY KEY,
  name        TEXT NOT NULL,
  exchange    TEXT NOT NULL DEFAULT 'US' REFERENCES exchanges(code),
  currency    TEXT,
  is_active   BOOLEAN NOT NULL DEFAULT true,
  synced_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_symbols_name_lower ON symbols (lower(name));
CREATE INDEX IF NOT EXISTS idx_symbols_symbol_prefix ON symbols (symbol text_pattern_ops);

-- Seed popular tickers so suggestions work before first Finnhub sync
INSERT INTO symbols (symbol, name, exchange, currency) VALUES
  ('AAPL', 'Apple Inc', 'US', 'USD'),
  ('MSFT', 'Microsoft Corp', 'US', 'USD'),
  ('NVDA', 'NVIDIA Corp', 'US', 'USD'),
  ('GOOGL', 'Alphabet Inc', 'US', 'USD'),
  ('AMZN', 'Amazon.com Inc', 'US', 'USD'),
  ('TSLA', 'Tesla Inc', 'US', 'USD'),
  ('META', 'Meta Platforms Inc', 'US', 'USD'),
  ('BRK.B', 'Berkshire Hathaway Inc', 'US', 'USD'),
  ('JPM', 'JPMorgan Chase & Co', 'US', 'USD'),
  ('V', 'Visa Inc', 'US', 'USD'),
  ('UNH', 'UnitedHealth Group Inc', 'US', 'USD'),
  ('XOM', 'Exxon Mobil Corp', 'US', 'USD'),
  ('JNJ', 'Johnson & Johnson', 'US', 'USD'),
  ('WMT', 'Walmart Inc', 'US', 'USD'),
  ('MA', 'Mastercard Inc', 'US', 'USD'),
  ('PG', 'Procter & Gamble Co', 'US', 'USD'),
  ('HD', 'Home Depot Inc', 'US', 'USD'),
  ('COST', 'Costco Wholesale Corp', 'US', 'USD'),
  ('ABBV', 'AbbVie Inc', 'US', 'USD'),
  ('CRM', 'Salesforce Inc', 'US', 'USD'),
  ('AMD', 'Advanced Micro Devices Inc', 'US', 'USD'),
  ('NFLX', 'Netflix Inc', 'US', 'USD'),
  ('BAC', 'Bank of America Corp', 'US', 'USD'),
  ('KO', 'Coca-Cola Co', 'US', 'USD'),
  ('PEP', 'PepsiCo Inc', 'US', 'USD'),
  ('DIS', 'Walt Disney Co', 'US', 'USD'),
  ('INTC', 'Intel Corp', 'US', 'USD'),
  ('CSCO', 'Cisco Systems Inc', 'US', 'USD'),
  ('ORCL', 'Oracle Corp', 'US', 'USD'),
  ('ADBE', 'Adobe Inc', 'US', 'USD')
ON CONFLICT (symbol) DO NOTHING;

CREATE TABLE IF NOT EXISTS suggested_symbols (
  symbol      TEXT PRIMARY KEY REFERENCES symbols(symbol),
  sort_order  INT NOT NULL,
  label       TEXT
);

INSERT INTO suggested_symbols (symbol, sort_order, label) VALUES
  ('AAPL', 1, 'Popular'),
  ('NVDA', 2, 'Popular'),
  ('MSFT', 3, 'Popular'),
  ('GOOGL', 4, 'Trending'),
  ('TSLA', 5, 'Trending'),
  ('AMZN', 6, 'Popular'),
  ('META', 7, NULL),
  ('JPM', 8, NULL),
  ('AMD', 9, 'Trending'),
  ('NFLX', 10, 'Popular'),
  ('COST', 11, NULL),
  ('CRM', 12, NULL),
  ('V', 13, NULL),
  ('MA', 14, NULL),
  ('WMT', 15, NULL),
  ('HD', 16, NULL),
  ('BAC', 17, NULL),
  ('DIS', 18, NULL),
  ('KO', 19, NULL),
  ('ORCL', 20, NULL)
ON CONFLICT (symbol) DO NOTHING;
