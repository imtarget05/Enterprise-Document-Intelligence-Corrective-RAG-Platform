"""
Action Agent - Phase 4.
Executes real-world actions:
  - send_email      - SMTP email via aiosmtplib
  - create_jira     - Jira REST API
  - create_notion   - Notion API
  - trigger_webhook - generic HTTP POST webhook
"""

import logging
from typing import Any, Dict, Optional

import httpx
from langchain_core.messages import HumanMessage
from llm_factory import LLMFactory

from graph.state import AgentState
from settings import settings
from tools.notification_tool import EmailNotifier, WebhookTrigger

logger = logging.getLogger(__name__)


class ActionAgent:
    def __init__(self):
        self._llm = LLMFactory.get_model(temperature=0.1)
        self._email = EmailNotifier()
        self._webhook = WebhookTrigger()

    # ------------------------------------------------------------------
    # LangGraph node
    # ------------------------------------------------------------------
    async def run(self, state: AgentState) -> AgentState:
        query = state["query"]
        logger.info("Action Agent processing: %s", query[:80])

        # Parse intent from query
        action_info = await self._parse_action(query)
        action_type = action_info.get("action_type", "send_email")
        payload = action_info.get("payload", {})
        payload["user_id"] = state["user_id"]

        # Get idempotency key from HITL approval for crash-safe execution
        idempotency_key = state.get("hitl_idempotency_key")
        approval_id = state.get("hitl_approval_id")

        result = await self.execute(action_type, payload, idempotency_key, approval_id)

        state["final_answer"] = self._format_result(action_type, result)
        state["action_result"] = result
        state["agent_type"] = "action"
        return state

    # ------------------------------------------------------------------
    # Standalone execution (called via /agent/action endpoint)
    # ------------------------------------------------------------------
    async def execute(
        self, action_type: str, payload: Dict[str, Any],
        idempotency_key: Optional[str] = None,
        approval_id: Optional[str] = None
    ) -> Dict[str, Any]:
        handlers = {
            "send_email": self._send_email,
            "create_jira": self._create_jira,
            "create_notion": self._create_notion,
            "send_teams_webhook": self._send_teams_webhook,
            "trigger_webhook": self._trigger_webhook,
        }
        handler = handlers.get(action_type)
        if not handler:
            return {"error": f"Unknown action type: {action_type}"}

        # If we have an idempotency key and approval_id, check if already executed
        if idempotency_key and approval_id:
            from hitl import hitl_store
            existing = await hitl_store.get(approval_id)
            if existing and existing.get("status") == "executed":
                logger.info("Action already executed for approval %s, returning cached result", approval_id)
                return existing.get("workflow_result", {"status": "already_executed"})

        result = await handler(payload)

        # If we have an approval_id, mark as executed
        if approval_id and idempotency_key:
            from hitl import hitl_store
            await hitl_store.complete(approval_id, result)

        return result

    # ------------------------------------------------------------------
    # Email
    # ------------------------------------------------------------------
    async def _send_email(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        to = payload.get("to", "")
        subject = payload.get("subject", "Smart Document Chatbot - Notification")
        body = payload.get("body", "")
        if not to:
            return {"error": "Missing 'to' field"}
        return await self._email.send(to=to, subject=subject, body=body)

    # ------------------------------------------------------------------
    # Jira
    # ------------------------------------------------------------------
    async def _create_jira(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not settings.jira_base_url or not settings.jira_api_token:
            logger.warning(
                "Jira action requested but JIRA_BASE_URL/JIRA_API_TOKEN not configured"
            )
            return {
                "error": "Jira not configured (JIRA_BASE_URL / JIRA_API_TOKEN missing)"
            }
        import base64

        credentials = base64.b64encode(
            f"{settings.jira_email}:{settings.jira_api_token}".encode()
        ).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "Content-Type": "application/json",
        }
        jira_body = {
            "fields": {
                "project": {"key": payload.get("project_key", "PROJ")},
                "summary": payload.get("summary", "Task from Smart Document Chatbot"),
                "description": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": payload.get("description", "")}
                            ],
                        }
                    ],
                },
                "issuetype": {"name": payload.get("issue_type", "Task")},
            }
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{settings.jira_base_url}/rest/api/3/issue",
                headers=headers,
                json=jira_body,
            )
            resp.raise_for_status()
            data = resp.json()
        return {
            "jira_key": data.get("key"),
            "url": f"{settings.jira_base_url}/browse/{data.get('key')}",
        }

    # ------------------------------------------------------------------
    # Notion
    # ------------------------------------------------------------------
    async def _create_notion(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not settings.notion_api_token:
            logger.warning(
                "Notion action requested but NOTION_API_TOKEN not configured"
            )
            return {"error": "Notion not configured (NOTION_API_TOKEN missing)"}
        headers = {
            "Authorization": f"Bearer {settings.notion_api_token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }
        body = {
            "parent": {"database_id": payload.get("database_id", "")},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.get("title", "New Page")}}]
                },
            },
            "children": [
                {
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {
                        "rich_text": [
                            {
                                "type": "text",
                                "text": {"content": payload.get("content", "")[:2000]},
                            }
                        ]
                    },
                }
            ],
        }
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.notion.com/v1/pages", headers=headers, json=body
            )
            resp.raise_for_status()
            data = resp.json()
        return {"notion_id": data.get("id"), "url": data.get("url")}

    # ------------------------------------------------------------------
    # Generic webhook
    # ------------------------------------------------------------------
    async def _trigger_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = payload.get("url", "")
        if not url:
            return {"error": "Missing 'url' field"}
        return await self._webhook.post(url=url, data=payload.get("data", {}))

    async def _send_teams_webhook(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = payload.get("url") or settings.teams_webhook_url
        if not url:
            logger.warning(
                "Teams webhook action requested but TEAMS_WEBHOOK_URL not configured"
            )
            return {"error": "Teams webhook not configured (TEAMS_WEBHOOK_URL missing)"}
        text = (
            payload.get("text") or payload.get("message") or payload.get("body") or ""
        )
        if not text:
            return {"error": "Missing Teams message text"}
        return await self._webhook.post(url=url, data={"text": text})

    # ------------------------------------------------------------------
    # Parse action intent from natural language
    # ------------------------------------------------------------------
    async def _parse_action(self, query: str) -> Dict[str, Any]:
        prompt = (
            f"Extract the action from the following user request. "
            f"Return a JSON with 'action_type' (one of: send_email, create_jira, create_notion, send_teams_webhook, trigger_webhook) "
            f"and 'payload' (relevant fields). No markdown.\n\nRequest: {query}"
        )
        try:
            import json
            import re

            resp = await self._llm.ainvoke([HumanMessage(content=prompt)])
            raw = resp.content.strip()
            match = re.search(r"\{.*\}", raw, re.DOTALL)
            if match:
                return json.loads(match.group())
        except Exception as exc:
            logger.warning("Action parsing failed: %s", exc)
        return {"action_type": "send_email", "payload": {}}

    @staticmethod
    def _format_result(action_type: str, result: Dict[str, Any]) -> str:
        if "error" in result:
            return f"Action failed: {result['error']}"
        labels = {
            "send_email": "Email sent",
            "create_jira": f"Jira ticket created: {result.get('jira_key', '')}",
            "create_notion": f"Notion page created: {result.get('url', '')}",
            "trigger_webhook": "Webhook triggered",
        }
        return labels.get(action_type, f"Action completed: {result}")
