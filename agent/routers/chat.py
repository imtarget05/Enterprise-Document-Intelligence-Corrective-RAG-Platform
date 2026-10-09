"""
Chat and real-time streaming endpoints (HTTP, SSE, and WebSocket).
"""

import asyncio
import json
import logging
import re
import time
from typing import AsyncIterator

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from ab_testing import ab_manager
from models import AgentRequest, AgentResponse
from security.guardrails import input_guardrails, output_guardrails
import state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["chat"])


async def stream_answer_tokens(answer: str) -> AsyncIterator[str]:
    """Yield answer text as natural token chunks without artificial delay."""
    if not answer:
        return
    tokens = re.findall(r"\S+\s*", answer)
    for token in tokens:
        yield token


@router.websocket(
    "/ws/{session_id}", dependencies=[Depends(state.verify_websocket_and_rate_limit)]
)
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    logger.info(f"WebSocket connected: session={session_id}")

    try:
        while True:
            data = await websocket.receive_text()
            payload = json.loads(data)
            query = payload.get("query", "")
            user_id = payload.get("user_id", session_id)
            document_ids = payload.get("document_ids", [])
            use_web_search = payload.get("use_web_search", False)

            logger.info(f"WebSocket query: session={session_id} query={query[:80]}")

            # Prompt-injection guard
            try:
                query = state.check_prompt_injection(query)
            except ValueError as inj_exc:
                await websocket.send_json(
                    {
                        "event": "error",
                        "data": {
                            "error": str(inj_exc),
                            "code": "prompt_injection_blocked",
                        },
                    }
                )
                continue

            # Input guardrail check
            input_report = input_guardrails.check(query)
            if not input_report.passed:
                blocked = [e for e in input_report.events if e.severity == "high"]
                if blocked:
                    await websocket.send_json(
                        {
                            "event": "error",
                            "data": {
                                "error": f"Input blocked by guardrails: {[e.message for e in blocked]}",
                                "code": "guardrail_blocked",
                            },
                        }
                    )
                    continue
                logger.warning("Input guardrail warnings: %s", input_report.events)

            await websocket.send_json({"event": "connected", "session_id": session_id})

            long_term_history = []
            if state._long_term_memory is not None:
                long_term_history = await state._long_term_memory.get_history(
                    session_id=session_id,
                    user_id=user_id,
                    limit=6,
                )

            await websocket.send_json(
                {
                    "event": "plan",
                    "data": {"agent_type": "rag", "plan": f"Processing: {query[:100]}"},
                }
            )

            if state._workflow is None:
                result = {
                    "final_answer": "ADK demo fallback is active.",
                    "agent_type": "adk",
                    "sources": [],
                    "confidence_score": 0.0,
                }
                await websocket.send_json(
                    {
                        "event": "token",
                        "data": {"text": result["final_answer"]},
                    }
                )
            else:
                ab_config = ab_manager.get_active_variant_config(
                    query_id=f"{session_id}:{query[:64]}"
                )
                result = await state._workflow.ainvoke(
                    {
                        "query": query,
                        "session_id": session_id,
                        "user_id": user_id,
                        "document_ids": document_ids or [],
                        "messages": [],
                        "long_term_history": long_term_history,
                        "retrieved_chunks": [],
                        "confidence_score": 0.0,
                        "agent_plan": "",
                        "agent_type": "",
                        "intent_override": payload.get("intent_override"),
                        "final_answer": "",
                        "sources": [],
                        "action_result": None,
                        "report_path": None,
                        "use_web_search": use_web_search,
                        "hybrid_search_enabled": True,
                        "ab_config": ab_config,
                    }
                )

                answer = result.get("final_answer", "")
                confidence = result.get("confidence_score", 0.0)
                output_report = output_guardrails.check(query, answer, confidence)
                if not output_report.passed:
                    logger.warning("Output guardrail warnings: %s", output_report.events)

                async for token in stream_answer_tokens(answer):
                    await websocket.send_json(
                        {
                            "event": "token",
                            "data": {"text": token},
                        }
                    )
                    await asyncio.sleep(0)

            if state._long_term_memory is not None:
                agent_type = result.get("agent_type", "rag")
                await state._long_term_memory.save_turn(
                    user_id, session_id, "user", query, agent_type
                )
                await state._long_term_memory.save_turn(
                    user_id,
                    session_id,
                    "assistant",
                    result.get("final_answer", ""),
                    agent_type,
                )

            sources = result.get("sources", [])
            if sources:
                await websocket.send_json(
                    {"event": "source", "data": {"sources": sources}}
                )

            await websocket.send_json(
                {
                    "event": "complete",
                    "data": {
                        "agent_type": result.get("agent_type", "rag"),
                        "confidence_score": result.get("confidence_score", 0.0),
                        "hitl_pending": bool(result.get("hitl_pending", False)),
                        "hitl_approval_id": result.get("hitl_approval_id"),
                    },
                }
            )

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: session={session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
        try:
            await websocket.send_json({"event": "error", "data": {"error": str(e)}})
        except Exception:
            logger.debug("Could not send error to disconnected WebSocket", exc_info=True)


@router.post(
    "/agent/invoke",
    response_model=AgentResponse,
    dependencies=[Depends(state.verify_and_rate_limit)],
)
async def invoke_agent(req: AgentRequest, request: Request):
    try:
        corr = state.get_correlation_ids()
        eff_trace = req.trace_id or (getattr(request.state, "trace_id", "") if hasattr(request, "state") else "") or corr.get("trace_id", "")
        eff_req = req.request_id or (getattr(request.state, "request_id", "") if hasattr(request, "state") else "") or corr.get("request_id", "")
        if eff_trace:
            state._trace_id_ctx.set(eff_trace)
        if eff_req:
            state._request_id_ctx.set(eff_req)

        logger.info(
            "Agent invoke: session=%s user=%s query=%s trace_id=%s request_id=%s",
            req.session_id,
            req.user_id,
            req.query[:80],
            eff_trace,
            eff_req,
        )

        try:
            safe_query = state.check_prompt_injection(req.query)
        except ValueError as inj_exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(inj_exc),
            )
        if safe_query != req.query:
            req = req.model_copy(update={"query": safe_query})

        input_report = input_guardrails.check(req.query)
        if not input_report.passed:
            blocked = [e for e in input_report.events if e.severity == "high"]
            if blocked:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Input blocked by guardrails: {[e.message for e in blocked]}",
                )
            logger.warning("Input guardrail warnings: %s", input_report.events)

        long_term_history = []
        if state._long_term_memory is not None:
            long_term_history = await state._long_term_memory.get_history(
                session_id=req.session_id,
                user_id=req.user_id,
                limit=6,
            )

        ab_config = ab_manager.get_active_variant_config(
            query_id=f"{req.session_id}:{req.query[:64]}"
        )
        if ab_config:
            logger.info(
                "A/B variant assigned: %s config=%s",
                ab_config.get("variant_id", "none"),
                {k: v for k, v in ab_config.items() if k != "variant_id"},
            )
        start_time = time.monotonic()

        if state._workflow is None:
            result = {
                "final_answer": "ADK demo fallback is active; LangGraph workflow is unavailable in this environment.",
                "agent_type": "adk",
                "sources": [],
                "confidence_score": 0.0,
                "action_result": None,
                "report_path": None,
            }
        else:
            result = await state._workflow.ainvoke(
                {
                    "query": req.query,
                    "session_id": req.session_id,
                    "user_id": req.user_id,
                    "document_ids": req.document_ids or [],
                    "messages": [],
                    "long_term_history": long_term_history,
                    "retrieved_chunks": [],
                    "confidence_score": 0.0,
                    "agent_plan": "",
                    "agent_type": "",
                    "intent_override": req.intent_override,
                    "final_answer": "",
                    "sources": [],
                    "action_result": None,
                    "report_path": None,
                    "use_web_search": req.use_web_search,
                    "hybrid_search_enabled": True,
                    "ab_config": ab_config,
                }
            )

        latency_ms = (time.monotonic() - start_time) * 1000

        action_result = result.get("action_result") or {}
        if action_result.get("status") == "store_unavailable":
            # Fail-closed: the approval store is down, so the action was NOT
            # executed. Surface HTTP 503 (not 200) so upstream callers and
            # circuit breakers treat this as an infra outage, not an answer.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=result.get("final_answer", "Approval store unavailable"),
            )

        if ab_config:
            try:
                ab_manager.log_result(
                    query_id=f"{req.session_id}:{req.query[:64]}",
                    variant_id=ab_config["variant_id"],
                    latency_ms=latency_ms,
                    confidence_score=result.get("confidence_score", 0.0),
                    answer_correct=result.get("confidence_score", 0) > 0.3,
                )
            except Exception as ab_exc:
                logger.debug("A/B logging failed: %s", ab_exc)

        if state._long_term_memory is not None:
            agent_type = result.get("agent_type", "rag")
            await state._long_term_memory.save_turn(
                req.user_id,
                req.session_id,
                "user",
                req.query,
                agent_type,
            )
            await state._long_term_memory.save_turn(
                req.user_id,
                req.session_id,
                "assistant",
                result.get("final_answer", ""),
                agent_type,
            )

        answer = result.get("final_answer", "")
        confidence = result.get("confidence_score", 0.0)
        output_report = output_guardrails.check(req.query, answer, confidence)
        if not output_report.passed:
            logger.warning("Output guardrail warnings: %s", output_report.events)

        corr = state.get_correlation_ids()
        eff_trace = corr.get("trace_id", "") or req.trace_id or ""

        try:
            from metrics import estimate_tokens, calculate_cost, record_llm_usage
            from settings import settings as _settings

            model = _settings.llm_chat_model
            prompt_tokens = int(result.get("prompt_tokens", 0) or 0)
            completion_tokens = int(result.get("completion_tokens", 0) or 0)
            if prompt_tokens == 0 and completion_tokens == 0:
                prompt_tokens = estimate_tokens(req.query)
                completion_tokens = estimate_tokens(answer)
            usage_meta = result.get("usage_metadata") or result.get("usage") or {}
            if isinstance(usage_meta, dict) and usage_meta:
                prompt_tokens = int(usage_meta.get("input_tokens", usage_meta.get("prompt_tokens", prompt_tokens)) or prompt_tokens)
                completion_tokens = int(usage_meta.get("output_tokens", usage_meta.get("completion_tokens", completion_tokens)) or completion_tokens)
            cost_usd = calculate_cost(prompt_tokens, completion_tokens, model)
            record_llm_usage(model, prompt_tokens, completion_tokens, cost_usd)
        except Exception as _e:
            logger.debug("Cost tracking failed: %s", _e)
            prompt_tokens, completion_tokens, cost_usd = 0, 0, 0.0

        return AgentResponse(
            session_id=req.session_id,
            answer=answer,
            agent_type=result.get("agent_type", "rag"),
            sources=result.get("sources", []),
            confidence_score=confidence,
            action_result=result.get("action_result"),
            hitl_pending=bool(result.get("hitl_pending", False)),
            hitl_approval_id=result.get("hitl_approval_id"),
            report_path=result.get("report_path"),
            trace_id=eff_trace or None,
            tokens_used=(prompt_tokens + completion_tokens),
            cost_usd=cost_usd,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Agent invoke failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))


async def stream_events(req: AgentRequest):
    try:
        logger.info(
            "Agent stream: session=%s user=%s query=%s",
            req.session_id,
            req.user_id,
            req.query[:80],
        )

        try:
            safe_query = state.check_prompt_injection(req.query)
        except ValueError as inj_exc:
            yield f"event: error\ndata: {json.dumps({'error': str(inj_exc), 'code': 'prompt_injection_blocked'})}\n\n"
            return
        if safe_query != req.query:
            req = req.model_copy(update={"query": safe_query})

        input_report = input_guardrails.check(req.query)
        if not input_report.passed:
            blocked = [e for e in input_report.events if e.severity == "high"]
            if blocked:
                yield f"event: error\ndata: {json.dumps({'error': f'Input blocked: {[e.message for e in blocked]}', 'code': 'guardrail_blocked'})}\n\n"
                return
            logger.warning("Input guardrail warnings: %s", input_report.events)

        long_term_history = []
        if state._long_term_memory is not None:
            long_term_history = await state._long_term_memory.get_history(
                session_id=req.session_id,
                user_id=req.user_id,
                limit=6,
            )

        plan_data = {
            "agent_type": "rag",
            "plan": f"Processing query: {req.query[:100]}",
        }
        yield f"event: plan\ndata: {json.dumps(plan_data)}\n\n"

        if state._workflow is None:
            result = {
                "final_answer": "ADK demo fallback is active; LangGraph workflow is unavailable.",
                "agent_type": "adk",
                "sources": [],
                "confidence_score": 0.0,
                "action_result": None,
                "report_path": None,
            }
            yield f"event: token\ndata: {json.dumps({'text': result['final_answer']})}\n\n"
        else:
            ab_config = ab_manager.get_active_variant_config(
                query_id=f"{req.session_id}:{req.query[:64]}"
            )
            result = await state._workflow.ainvoke(
                {
                    "query": req.query,
                    "session_id": req.session_id,
                    "user_id": req.user_id,
                    "document_ids": req.document_ids or [],
                    "messages": [],
                    "long_term_history": long_term_history,
                    "retrieved_chunks": [],
                    "confidence_score": 0.0,
                    "agent_plan": "",
                    "agent_type": "",
                    "intent_override": req.intent_override,
                    "final_answer": "",
                    "sources": [],
                    "action_result": None,
                    "report_path": None,
                    "use_web_search": req.use_web_search,
                    "hybrid_search_enabled": True,
                    "ab_config": ab_config,
                }
            )

            answer = result.get("final_answer", "")
            confidence = result.get("confidence_score", 0.0)
            output_report = output_guardrails.check(req.query, answer, confidence)
            if not output_report.passed:
                logger.warning("Output guardrail warnings: %s", output_report.events)

            async for token in stream_answer_tokens(answer):
                yield f"event: token\ndata: {json.dumps({'text': token})}\n\n"
                await asyncio.sleep(0)

        if state._long_term_memory is not None:
            agent_type = result.get("agent_type", "rag")
            await state._long_term_memory.save_turn(
                req.user_id, req.session_id, "user", req.query, agent_type
            )
            await state._long_term_memory.save_turn(
                req.user_id,
                req.session_id,
                "assistant",
                result.get("final_answer", ""),
                agent_type,
            )

        sources = result.get("sources", [])
        if sources:
            yield f"event: source\ndata: {json.dumps({'sources': sources})}\n\n"

        yield f"event: complete\ndata: {json.dumps({'agent_type': result.get('agent_type', 'rag'), 'confidence_score': result.get('confidence_score', 0.0), 'hitl_pending': bool(result.get('hitl_pending', False)), 'hitl_approval_id': result.get('hitl_approval_id')})}\n\n"

    except Exception as exc:
        logger.exception("Agent stream failed: %s", exc)
        yield f"event: error\ndata: {json.dumps({'error': str(exc)})}\n\n"


@router.post("/agent/invoke-stream", dependencies=[Depends(state.verify_and_rate_limit)])
async def invoke_agent_stream(req: AgentRequest):
    return StreamingResponse(
        stream_events(req),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
