"""
Orchestrator Agent – analyses the user query, produces a plan and decides
which specialist sub-agent should handle it.

Intent classification:
  • rag       – direct Q&A against uploaded documents
  • report    – user asks to generate a report / summary document
  • compare   – user asks to compare two or more documents / topics
  • research  – general research question, needs web search
  • action    – user asks to DO something (send email, create task …)
"""

import logging
import re

from langchain_core.messages import HumanMessage, SystemMessage

from llm_factory import LLMFactory
from graph.state import AgentState
from prompts import render_prompt, PromptNotFoundError

logger = logging.getLogger(__name__)


class OrchestratorAgent:
    def __init__(self):
        self._llm = LLMFactory.get_reasoning_model(temperature=0.0)

    async def run(self, state: AgentState) -> AgentState:
        query = state["query"]
        logger.info("Orchestrator analysing: %s", query[:120])

        if state.get("intent_override"):
            intent = state["intent_override"]
            state["agent_type"] = intent
            state["agent_plan"] = f"Intent overridden to: {intent}"
            logger.info("Intent override: %s", intent)
            return state

        try:
            rendered = render_prompt("orchestrator_intent", query=query)
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=rendered),
                    HumanMessage(content=query),
                ]
            )
            raw = response.content.strip()

            json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if json_match:
                import json

                parsed = json.loads(json_match.group())
                intent = parsed.get("intent", "rag")
                plan = parsed.get("plan", "")
            else:
                intent, plan = self._heuristic_intent(query)

        except PromptNotFoundError:
            logger.warning("orchestrator_intent prompt not found, using fallback")
            fallback_prompt = (
                'You are an intelligent orchestrator for a document Q&A platform.\n'
                'Analyze the user\'s query and output EXACTLY one JSON object (no markdown) with two keys:\n'
                '  "intent": one of ["rag", "report", "compare", "research", "action", "engineering"]\n'
                '  "plan":   a short 1-sentence description of what needs to be done'
            )
            response = await self._llm.ainvoke(
                [
                    SystemMessage(content=fallback_prompt),
                    HumanMessage(content=query),
                ]
            )
            raw = response.content.strip()
            json_match = re.search(r"\{[^}]+\}", raw, re.DOTALL)
            if json_match:
                import json

                parsed = json.loads(json_match.group())
                intent = parsed.get("intent", "rag")
                plan = parsed.get("plan", "")
            else:
                intent, plan = self._heuristic_intent(query)
        except Exception as exc:
            logger.warning(
                "Orchestrator LLM call failed: %s – falling back to heuristic", exc
            )
            intent, plan = self._heuristic_intent(query)

        # A document-scoped question must not silently become open-web research.
        # The caller has already authorized a specific set of documents.
        document_question = re.match(r"^\s*(?:according to .{0,100},?\s*)?(?:what|when|where|who|how|which|does|is|are)\b", query, re.IGNORECASE)
        if state.get("document_ids") and (
            (intent == "research" and not state.get("use_web_search"))
            or (intent == "report" and document_question)
        ):
            intent = "rag"
            plan = "Answer from the selected documents using RAG."
        state["agent_type"] = intent
        state["agent_plan"] = plan
        logger.info("Orchestrator decision → intent=%s plan=%s", intent, plan)
        return state

    @staticmethod
    def _heuristic_intent(query: str):
        q = query.lower()
        if any(
            k in q
            for k in (
                "8d",
                "root cause",
                "corrective action",
                "failure",
                "test report",
                "engineering report",
            )
        ):
            return (
                "engineering",
                "Analyze engineering evidence and produce an 8D-style report.",
            )
        if any(
            k in q for k in ("report", "pdf", "summary", "tóm tắt", "báo cáo", "xuất")
        ):
            return "report", "Generate a report from documents."
        if any(k in q for k in ("compare", "so sánh", "difference", "diff", "vs")):
            return "compare", "Compare documents."
        if any(
            k in q for k in ("search web", "tìm kiếm", "news", "latest", "researcher")
        ):
            return "research", "Research via web."
        if any(
            k in q
            for k in (
                "send email",
                "gửi email",
                "jira",
                "notion",
                "task",
                "webhook",
                "trigger",
            )
        ):
            return "action", "Execute an action."
        return "rag", "Answer from documents using RAG."
