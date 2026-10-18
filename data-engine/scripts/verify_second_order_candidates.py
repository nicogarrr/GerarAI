"""Read existing tenant news and assert indirect candidate hygiene. Never writes peers."""
from __future__ import annotations

import argparse
import json

from sqlalchemy import select

from app.core.database import SessionLocal
from app.models import Company, NewsEvent
from app.services.second_order_news_service import analyze_second_order


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--tenant-id', type=int, required=True)
    parser.add_argument('--event-id', type=int, action='append', required=True)
    parser.add_argument('--use-llm', action='store_true', help='Reserves bounded free LLM quota; default is deterministic replay')
    args = parser.parse_args()
    with SessionLocal() as db:
        db.info['tenant_id'] = args.tenant_id
        for event_id in args.event_id:
            event = db.scalar(select(NewsEvent).where(NewsEvent.id == event_id, NewsEvent.tenant_id == args.tenant_id))
            if event is None:
                raise SystemExit(f'Event {event_id} not found in tenant {args.tenant_id}')
            company = db.get(Company, event.company_id) if event.company_id else None
            ticker = company.ticker.strip().upper() if company else None
            result = analyze_second_order(db, event, use_llm=args.use_llm)
            tickers = [row['ticker'].strip().upper() for row in result['candidates']]
            assert len(tickers) == len(set(tickers)), 'Duplicate ticker'
            assert ticker not in tickers, 'Subject in indirect candidates'
            assert result['source_verified'] is False
            assert all(row['status'] == 'hipótesis_no_verificada' for row in result['candidates'])
            print(json.dumps(result, ensure_ascii=False, default=str))
        db.rollback()


if __name__ == '__main__':
    main()
