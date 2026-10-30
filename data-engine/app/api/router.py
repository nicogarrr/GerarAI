from fastapi import APIRouter

from app.api.routes import (
    alerts,
    asts,
    bottlenecks,
    cache,
    calendar,
    chat,
    companies,
    company_events,
    corporate_actions,
    data_health,
    db_metrics,
    earnings,
    export,
    filing_intelligence,
    insider,
    investors,
    knowledge,
    knowledge_graph,
    knowledge_rag,
    language,
    macro_calendar,
    market,
    market_context,
    memory,
    money_flows,
    news,
    obsidian,
    ownership,
    paper_trading,
    plan,
    portfolio,
    portfolio_images,
    portfolio_moves,
    privacy,
    propicks,
    research_assistant,
    reviews,
    risk,
    screeners,
    search,
    settings,
    sources,
    taxes,
    telegram_link,
    thesis,
    thesis_projection,
    thesis_scenarios,
    valuation,
    watchlist,
    work_products,
    workflows,
)

# NOTE: app.api.routes.health NO se registra aquí a propósito. main.py monta
# su router directamente con prefix="/api" y SIN dependencies, porque /api/health
# debe ser público (sin firma Research OS) para orquestación/monitoreo. Registrarlo
# en api_router lo haría heredar la auth de main.py.

api_router = APIRouter()
api_router.include_router(bottlenecks.router, prefix="/bottlenecks", tags=["bottlenecks"])
api_router.include_router(cache.router, prefix="/cache", tags=["cache"])
api_router.include_router(data_health.router, prefix="/data-health", tags=["data-health"])
api_router.include_router(db_metrics.router, tags=["admin"])
api_router.include_router(alerts.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(telegram_link.router, prefix="/alerts", tags=["alerts"])
api_router.include_router(calendar.router, prefix="/calendar", tags=["calendar"])
api_router.include_router(companies.router, prefix="/companies", tags=["companies"])
api_router.include_router(company_events.router, prefix="/companies", tags=["companies"])
api_router.include_router(
    corporate_actions.router, prefix="/corporate-actions", tags=["corporate-actions"]
)
api_router.include_router(earnings.router, prefix="/earnings", tags=["earnings"])
api_router.include_router(export.router, prefix="/export", tags=["export"])
api_router.include_router(insider.router, prefix="/insider", tags=["insider"])
api_router.include_router(portfolio.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(portfolio_images.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(portfolio_moves.router, prefix="/portfolio", tags=["portfolio"])
api_router.include_router(privacy.router, prefix="/privacy", tags=["privacy"])
api_router.include_router(propicks.router, prefix="/propicks", tags=["propicks"])
api_router.include_router(plan.router, prefix="/plan", tags=["plan"])
api_router.include_router(ownership.router, prefix="/ownership", tags=["ownership"])
api_router.include_router(investors.router, prefix="/investors", tags=["investors"])
api_router.include_router(taxes.router, prefix="/taxes", tags=["taxes"])
api_router.include_router(thesis.router, prefix="/thesis", tags=["thesis"])
api_router.include_router(
    thesis_projection.router, prefix="/companies", tags=["companies"]
)
api_router.include_router(obsidian.router, prefix="/thesis", tags=["thesis"])
api_router.include_router(obsidian.vault_router, prefix="/obsidian", tags=["obsidian"])
api_router.include_router(valuation.router, prefix="/valuation", tags=["valuation"])
api_router.include_router(watchlist.router, prefix="/watchlist", tags=["watchlist"])
api_router.include_router(
    work_products.router, prefix="/work-products", tags=["work-products"]
)
api_router.include_router(news.router, prefix="/news", tags=["news"])
api_router.include_router(risk.router, prefix="/risk", tags=["risk"])
api_router.include_router(reviews.router, prefix="/reviews", tags=["reviews"])
api_router.include_router(research_assistant.router, prefix="/research", tags=["research-assistant"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(knowledge.router, prefix="/knowledge", tags=["knowledge"])
api_router.include_router(
    knowledge_rag.router, prefix="/knowledge-rag", tags=["knowledge-rag"]
)
api_router.include_router(
    knowledge_graph.router, prefix="/knowledge-graph", tags=["knowledge-graph"]
)
api_router.include_router(search.router, prefix="/search", tags=["search"])
api_router.include_router(screeners.router, prefix="/screeners", tags=["screeners"])
api_router.include_router(memory.router, prefix="/memory", tags=["memory"])
api_router.include_router(sources.router, prefix="/sources", tags=["sources"])
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
# /settings/language: preferencia de idioma de generacion del tenant (i18n B).
api_router.include_router(language.router, prefix="/settings", tags=["settings"])
api_router.include_router(market.router, prefix="/market", tags=["market"])
api_router.include_router(market_context.router, prefix="/market", tags=["market"])
api_router.include_router(money_flows.router, prefix="/market/flows", tags=["market", "flows"])
api_router.include_router(asts.router, prefix="/market/asts", tags=["market", "asts"])
api_router.include_router(
    macro_calendar.router, prefix="/macro-calendar", tags=["macro-calendar"]
)
api_router.include_router(workflows.router, prefix="/workflows", tags=["workflows"])

api_router.include_router(paper_trading.router, prefix="/paper-trading", tags=["paper-trading"])
api_router.include_router(filing_intelligence.router, prefix="/companies", tags=["companies"])

api_router.include_router(
    thesis_scenarios.router, prefix="/companies", tags=["companies"]
)
