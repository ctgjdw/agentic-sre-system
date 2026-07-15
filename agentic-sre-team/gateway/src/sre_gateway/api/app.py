import asyncio
import contextlib
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from sqlalchemy import text

from sre_gateway.api import activity, cases, governance, health, webhooks
from sre_gateway.audit import AuditWriter
from sre_gateway.budget import BudgetEnforcer, load_budgets
from sre_gateway.channels.log import LogChannel
from sre_gateway.channels.telegram import TelegramChannel
from sre_gateway.db.engine import make_engine, make_sessionmaker
from sre_gateway.environment import load_environment
from sre_gateway.graph import make_checkpointer
from sre_gateway.graph.build import build_graph
from sre_gateway.graph.decisions import apply_decision
from sre_gateway.graph.deps import GraphDeps
from sre_gateway.graph.grafana_links import LinkBuilder
from sre_gateway.graph.runner import CaseRunner
from sre_gateway.holmes.client import HolmesClient
from sre_gateway.intake.grouping import CorrelationGrouping, load_grouping
from sre_gateway.intake.noise import NoiseControl
from sre_gateway.intake.poller_grafana import GrafanaPoller
from sre_gateway.intake.reports import handle_report
from sre_gateway.intake.scorer import HeuristicScorer
from sre_gateway.intake.scorer_llm import LlmScorer
from sre_gateway.intake.service import IntakeService
from sre_gateway.llm.factory import ModelFactory, load_models_config
from sre_gateway.manifests import load_manifests
from sre_gateway.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.audit = AuditWriter(app.state.sessionmaker)

        models = ModelFactory(load_models_config(settings.models_config_path),
                              script_dir=settings.fake_script_dir)
        manifests = load_manifests(settings.config_dir / "agents")
        environment = load_environment(settings.config_dir / "environment.yaml")
        budget = BudgetEnforcer(app.state.sessionmaker,
                                load_budgets(settings.config_dir / "budgets.yaml"))
        holmes = HolmesClient(settings.holmes_url)
        channel = LogChannel()
        deps = GraphDeps(settings=settings, sessionmaker=app.state.sessionmaker,
                         audit=app.state.audit, models=models, manifests=manifests,
                         budget=budget, holmes=holmes, channel=channel,
                         environment=environment, links=LinkBuilder(settings))
        app.state.deps = deps

        grouping = CorrelationGrouping(load_grouping(settings.config_dir / "grouping.yaml"))
        noise = NoiseControl(app.state.sessionmaker, app.state.audit, grouping=grouping)

        async with make_checkpointer(settings.database_url) as checkpointer:
            graph = build_graph(deps, checkpointer)
            runner = CaseRunner(deps, graph)
            app.state.runner = runner

            async def _on_opened(case_id: str) -> None:
                # triage re-reads kind/title/everything from the case row, so the
                # hook only needs the id.
                await runner.start(case_id, {"case_id": case_id})

            app.state.intake = IntakeService(app.state.sessionmaker, app.state.audit, noise,
                                             on_case_opened=_on_opened)

            # Swap deps.channel to Telegram BEFORE relaunch_open_cases() so relaunched
            # cases (and every subsequent send) route to Telegram instead of LogChannel.
            # Nodes read deps.channel at call-time, so this reassignment is sufficient.
            # Explicit enable flag (default off), NOT mere token presence: the gateway
            # container loads the real .env via env_file, so keying off the token alone
            # would auto-activate Telegram (channel swap + live long-poll) under the fake
            # profile too, breaking `make smoke`/`make e2e` determinism (a live getUpdates
            # loop racing apply_decision). Same precedent as grafana_poll_enabled. The fake
            # profile leaves telegram_enabled unset -> LogChannel, no polling.
            channel_tg: TelegramChannel | None = None
            if (settings.telegram_enabled and settings.telegram_bot_token
                    and settings.telegram_chat_id):
                # fake profile keeps the heuristic scorer so `make smoke` stays
                # deterministic and never makes a real provider call for chatter.
                scorer = (HeuristicScorer() if settings.models_profile == "fake"
                          else LlmScorer(models, app.state.audit))

                async def _on_decision(case_id: str, gate: str, decision: str,
                                       decided_by: str) -> str:
                    try:
                        await apply_decision(app.state.sessionmaker, runner, case_id, gate,
                                             decision=decision, decided_by=decided_by,
                                             channel="telegram")
                    except HTTPException as err:
                        return str(err.detail)
                    # Short toast shown on the tapped button; the gate node posts the full
                    # decision echo to the group. Keep it accurate to what happens next:
                    # a reject loops back to a redraft, gate-1 approve drafts the runbook,
                    # only a gate-2 approve publishes.
                    if decision == "reject":
                        return "Recorded - sending back for a redraft"
                    if gate == "rca":
                        return "Recorded - drafting the runbook next"
                    return "Recorded - publishing next"

                async def _on_report(text_: str, reporter: str) -> str:
                    return await handle_report(app.state.intake, scorer, text_, reporter)

                channel_tg = TelegramChannel(settings, on_decision=_on_decision,
                                            on_report=_on_report, health=app.state.health)
                deps.channel = channel_tg  # swap: all outbound + gate buttons -> Telegram
            else:
                app.state.health["telegram"] = "disabled"

            try:
                async with app.state.sessionmaker() as s:
                    await s.execute(text("SELECT 1"))
                app.state.health["db"] = "ok"
            except Exception:
                # A down DB should surface as degraded health at request time, not a boot failure.
                app.state.health["db"] = "degraded"

            await runner.relaunch_open_cases()
            # Start both background tasks LAST so a relaunch failure can't orphan them
            # (they would keep running with no cancel path). Gate each on its own config:
            # without a grafana token the poller would loop on 401s; without a telegram
            # token there is nothing to poll.
            poller_task: asyncio.Task | None = None
            if (settings.grafana_poll_enabled and settings.grafana_url
                    and settings.grafana_sa_token):
                poller = GrafanaPoller(settings, app.state.intake, app.state.audit,
                                       app.state.health)
                poller_task = asyncio.create_task(poller.run())
            else:
                app.state.health["grafana_poller"] = "disabled"
            telegram_task: asyncio.Task | None = None
            if channel_tg is not None:
                telegram_task = asyncio.create_task(channel_tg.run_polling())
            yield
            if poller_task is not None:
                poller_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await poller_task
            if telegram_task is not None:
                telegram_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await telegram_task
            await runner.stop()
        await engine.dispose()

    app = FastAPI(title="sre-gateway", lifespan=lifespan)
    app.state.settings = settings
    app.state.health = {}
    app.include_router(health.router, prefix="/api")
    app.include_router(webhooks.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    app.include_router(governance.router, prefix="/api")
    app.include_router(activity.router, prefix="/api")
    return app
