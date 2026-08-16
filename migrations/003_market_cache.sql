-- Market cache tables (Finnhub quote/candle/news caches)

CREATE TABLE IF NOT EXISTS quote_cache (
  symbol          TEXT PRIMARY KEY REFERENCES symbols(symbol),
  price           NUMERIC(18,4),
  change          NUMERIC(18,4),
  change_pct      NUMERIC(10,4),
  prev_close      NUMERIC(18,4),
  fetched_at      TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS candles (
  symbol      TEXT NOT NULL REFERENCES symbols(symbol),
  resolution  TEXT NOT NULL,
  bar_time    TIMESTAMPTZ NOT NULL,
  open        NUMERIC(18,4),
  high        NUMERIC(18,4),
  low         NUMERIC(18,4),
  close       NUMERIC(18,4),
  volume      BIGINT,
  PRIMARY KEY (symbol, resolution, bar_time)
);

CREATE TABLE IF NOT EXISTS news_articles (
  id            TEXT PRIMARY KEY,
  symbol        TEXT NOT NULL REFERENCES symbols(symbol),
  headline      TEXT NOT NULL,
  source        TEXT,
  url           TEXT,
  published_at  TIMESTAMPTZ,
  fetched_at    TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_news_symbol ON news_articles (symbol, published_at DESC);
