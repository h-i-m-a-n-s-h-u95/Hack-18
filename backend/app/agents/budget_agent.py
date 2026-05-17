"""
Budget Agent Implementation with LangChain Tools and Redis Pub/Sub
"""

from typing import Dict, Any, List, Optional
import logging
import json
import re
from datetime import datetime

from app.agents.base_agent import BaseAgent, AgentType, StreamingUpdateType
from app.tools.budget_tools import BUDGET_TOOLS, calculate_complete_budget, compare_budget_categories
from app.messaging.redis_client import RedisClient
from app.services.budget_service import BudgetService
from app.core.state import BudgetBreakdown


class BudgetAgent(BaseAgent):
    """Budget Agent — Financial planning and cost estimation"""

    def __init__(
        self,
        redis_client: RedisClient,
        groq_api_key: str = None,
        model_name: str = "llama-3.3-70b-versatile",
    ):
        super().__init__(
            name="Quartermaster",
            role="Budget Planner & Financial Advisor",
            expertise="Cost estimation, budget optimization, and financial planning for travel",
            agent_type=AgentType.BUDGET,
            redis_client=redis_client,
            tools=BUDGET_TOOLS,
            groq_api_key=groq_api_key,
            model_name=model_name,
        )
        self.budget_service = BudgetService()

    def get_system_prompt(self) -> str:
        return f"""
You are {self.name}, a {self.role}.

Your job:
1. Analyse travel costs (transport, accommodation, food, activities)
2. Provide practical budget recommendations
3. Suggest cost-saving opportunities
4. Warn about hidden costs
5. Recommend budget allocation strategies
6. Provide specific transport recommendations (train names, booking tips)
7. Optimise budgets for Indian travel context

Expertise: {self.expertise}

All costs are in Indian Rupees (INR). Indian travel context:
- Train travel is common and economical (Sleeper, AC 3-Tier, AC 2-Tier classes)
- Budget hotels: ₹1500/night | Mid-range: ₹3000/night | Luxury: ₹6000/night
- Food: ₹500/day (budget) | ₹1200/day (mid-range) | ₹2500/day (luxury)
- Activities: ₹300/day (budget) | ₹800/day (mid-range) | ₹2000/day (luxury)

Always provide practical, money-conscious advice in INR.
Use IRCTC for trains, MakeMyTrip/GoIbibo for buses.

CRITICAL RESPONSE FORMAT:
Write 3-4 sentences of analysis, then output EXACTLY one JSON block like this:

```json
{{
    "revised_budget": {{
        "total": 0,
        "transportation": 0,
        "accommodation": 0,
        "food": 0,
        "activities": 0,
        "contingency": 0
    }},
    "recommended_transport": {{
        "mode": "train",
        "details": "Ajmer Shatabdi from Delhi to Jaipur",
        "estimated_cost": 0
    }},
    "key_recommendations": [
        "tip 1",
        "tip 2",
        "tip 3"
    ],
    "cost_per_person": 0,
    "recommended_duration": 3
}}
```

Do NOT put any text after the closing ``` fence.
"""

    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        payload        = request.get("payload", {})
        session_id     = request.get("session_id")

        destination    = payload.get("destination")
        travel_dates   = payload.get("travel_dates", [])
        travelers_count = int(payload.get("travelers_count", 1))
        budget_range   = payload.get("budget_range", "mid-range")
        route_data     = payload.get("route_data")
        distance_km    = payload.get("distance_km")

        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")
        if travelers_count < 1:
            raise ValueError("travelers_count must be at least 1")

        # Normalise budget category
        budget_category = (budget_range or "mid-range").lower().strip()
        if budget_category not in ("budget", "mid-range", "luxury"):
            budget_category = "mid-range"

        self.log_action("Calculating budget", f"{budget_category} / {travelers_count} travelers")

        # Extract distance
        if not distance_km and route_data:
            distance_km = self._extract_distance_km(route_data)
        if not distance_km or distance_km <= 0:
            distance_km = 200

        # Transport mode
        transport_mode = "driving"
        if isinstance(route_data, dict):
            transport_mode = route_data.get("transport_mode", "driving")

        # ── Step 1: calculate budget ──────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Calculating transportation costs", progress_percent=25,
        )

        budget_result = await calculate_complete_budget.ainvoke({
            "distance_km":    distance_km,
            "transport_mode": transport_mode,
            "travel_dates":   travel_dates,
            "travelers_count": travelers_count,
            "budget_category": budget_category,
        })

        if "error" in budget_result:
            raise Exception(f"Budget calculation failed: {budget_result['error']}")

        # ── Step 2: comparison ────────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Analysing accommodation and activity costs", progress_percent=50,
            data={"initial_budget_calculated": True},
        )

        comparison_result = await compare_budget_categories.ainvoke({
            "distance_km":    distance_km,
            "transport_mode": transport_mode,
            "travel_dates":   travel_dates,
            "travelers_count": travelers_count,
        })

        # ── Step 3: LLM analysis ──────────────────────────────────────────────
        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Generating budget recommendations", progress_percent=75,
        )

        raw_analysis = await self._generate_budget_analysis(
            budget_result=budget_result,
            comparison_result=comparison_result,
            destination=destination,
            travel_dates=travel_dates,
            travelers_count=travelers_count,
            budget_range=budget_category,
            session_id=session_id,
        )

        # ── Step 4: extract structured data & clean prose ─────────────────────
        structured_data  = self._extract_structured_budget_data(raw_analysis)
        clean_analysis   = self._strip_json_from_analysis(raw_analysis)

        # Build final budget dict from calculated values
        breakdown_dict = budget_result.get("breakdown", {})
        final_budget = {
            "total":          budget_result.get("total", 0),
            "transportation": breakdown_dict.get("transportation", {}).get("total", 0),
            "accommodation":  breakdown_dict.get("accommodation",  {}).get("total", 0),
            "food":           breakdown_dict.get("food",           {}).get("total", 0),
            "activities":     breakdown_dict.get("activities",     {}).get("total", 0),
            "currency":       "INR",
        }

        transport_recommendations = {}
        key_recommendations       = []

        # Override with LLM values if successfully parsed
        if structured_data and "revised_budget" in structured_data:
            revised = structured_data["revised_budget"]
            for key in ("total", "transportation", "accommodation", "food", "activities"):
                if revised.get(key):
                    final_budget[key] = revised[key]
            transport_recommendations = structured_data.get("recommended_transport", {})
            key_recommendations       = structured_data.get("key_recommendations", [])

        cost_per_person = (
            final_budget["total"] / travelers_count if travelers_count > 0
            else final_budget["total"]
        )

        await self._send_streaming_update(
            session_id=session_id, update_type=StreamingUpdateType.PROGRESS,
            message="Finalising budget report", progress_percent=90,
        )

        self.log_action("Budget complete", f"Total: ₹{final_budget['total']:,.0f}")

        return {
            "budget_breakdown":        final_budget,
            "budget_analysis":         clean_analysis,   # ← no JSON fences
            "structured_data":         structured_data or {},
            "transport_recommendations": transport_recommendations,
            "recommendations":         key_recommendations,
            "cost_per_person":         round(cost_per_person, 2),
            "destination":             destination,
            "travelers_count":         travelers_count,
            "budget_category":         budget_category,
            "comparison":              comparison_result.get("comparison", {}),
            "days":                    len(travel_dates),
            "distance_km":             distance_km,
        }

    # ── LLM helpers ───────────────────────────────────────────────────────────

    async def _generate_budget_analysis(
        self,
        budget_result: Dict[str, Any],
        comparison_result: Dict[str, Any],
        destination: str,
        travel_dates: List[str],
        travelers_count: int,
        budget_range: str,
        session_id: str,
    ) -> str:
        budget_text = self._format_budget_for_llm(budget_result, comparison_result)
        user_input = f"""
Destination: {destination}
Travel Dates: {', '.join(travel_dates)} ({len(travel_dates)} days)
Travelers: {travelers_count}
Budget preference: {budget_range}

Current budget calculation:
{budget_text}

Provide:
1. 3-4 sentence realistic analysis of the budget for {destination}
2. Specific transport recommendation (train name + platform)
3. Optimised budget breakdown
4. 3 practical money-saving tips

Then output the JSON block exactly as specified in the system prompt.
"""
        try:
            return await self.invoke_llm(
                system_prompt=self.get_system_prompt(),
                user_input=user_input,
                session_id=session_id,
                stream_progress=False,
            )
        except Exception as e:
            self.log_error("LLM budget analysis failed", str(e))
            return self._get_fallback_summary(budget_result)

    def _format_budget_for_llm(
        self, budget_result: Dict[str, Any], comparison_result: Dict[str, Any]
    ) -> str:
        total     = budget_result.get("total", 0)
        breakdown = budget_result.get("breakdown", {})
        lines = [
            f"CATEGORY: {budget_result.get('budget_category', 'mid-range').upper()}",
            f"TOTAL: ₹{total:,.0f}",
            f"Transportation: ₹{breakdown.get('transportation', {}).get('total', 0):,.0f}",
            f"Accommodation:  ₹{breakdown.get('accommodation',  {}).get('total', 0):,.0f}",
            f"Food:           ₹{breakdown.get('food',           {}).get('total', 0):,.0f}",
            f"Activities:     ₹{breakdown.get('activities',     {}).get('total', 0):,.0f}",
            f"Per person:     ₹{budget_result.get('per_person', 0):,.0f}",
        ]
        if comparison_result and "comparison" in comparison_result:
            lines.append("COMPARISON:")
            for cat, data in comparison_result["comparison"].items():
                lines.append(f"  {cat}: ₹{data.get('total', 0):,.0f}")
        return "\n".join(lines)

    def _get_fallback_summary(self, budget_result: Dict[str, Any]) -> str:
        total      = budget_result.get("total", 0)
        travelers  = budget_result.get("travelers_count", 1)
        per_person = budget_result.get("per_person", 0)
        return (
            f"Total estimated cost: ₹{total:,.0f} for {travelers} travelers "
            f"(₹{per_person:,.0f} per person). Book trains via IRCTC and hotels "
            f"via MakeMyTrip for best rates."
        )

    # ── JSON extraction ───────────────────────────────────────────────────────

    def _extract_structured_budget_data(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """
        Robustly extract the JSON block from the LLM response.
        Tries three strategies in order:
          1. Fenced ```json ... ``` block
          2. First bare { ... } that contains 'revised_budget'
          3. Any valid JSON object in the string
        """
        if not llm_response:
            return None

        # Strategy 1: fenced block
        fenced = re.search(r"```json\s*(\{.*?\})\s*```", llm_response, re.DOTALL)
        if fenced:
            try:
                return json.loads(fenced.group(1))
            except json.JSONDecodeError:
                pass

        # Strategy 2: find the outermost { } that contains 'revised_budget'
        start = llm_response.find("{")
        while start != -1:
            depth  = 0
            in_str = False
            escape = False
            for i, ch in enumerate(llm_response[start:], start):
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_str:
                    escape = True
                    continue
                if ch == '"':
                    in_str = not in_str
                    continue
                if in_str:
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = llm_response[start: i + 1]
                        if "revised_budget" in candidate:
                            try:
                                return json.loads(candidate)
                            except json.JSONDecodeError:
                                pass
                        break
            start = llm_response.find("{", start + 1)

        self.logger.warning("Could not extract structured JSON from LLM budget response")
        return None

    def _strip_json_from_analysis(self, llm_response: str) -> str:
        """
        Remove the JSON block (and its fence) from the LLM response so
        budget_analysis contains only the human-readable prose.
        """
        # Remove fenced block
        clean = re.sub(r"```json.*?```", "", llm_response, flags=re.DOTALL)
        # Remove any leftover bare JSON that starts with {
        clean = re.sub(r"\{[\s\S]*\}", "", clean)
        # Collapse excess blank lines
        clean = re.sub(r"\n{3,}", "\n\n", clean)
        return clean.strip()

    # ── Utility ───────────────────────────────────────────────────────────────

    def _extract_distance_km(self, route_data: Dict[str, Any]) -> float:
        if not route_data:
            return 0
        distance_m = route_data.get("distance_meters")
        if distance_m:
            return distance_m / 1000
        distance_str = route_data.get("distance", "")
        km = re.search(r"(\d+(?:\.\d+)?)\s*km", distance_str.lower())
        if km:
            return float(km.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*m\b", distance_str.lower())
        if m:
            return float(m.group(1)) / 1000
        return 0


# ==================== STANDALONE RUNNER ====================

async def run_budget_agent_standalone():
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    import asyncio

    redis_client = get_redis_client()
    await redis_client.connect()

    agent = BudgetAgent(
        redis_client=redis_client,
        groq_api_key=settings.groq_api_key,
        model_name=settings.model_name,
    )
    await agent.start()

    print(f"✅ Budget Agent running — {RedisChannels.get_request_channel('budget')}")
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await agent.stop()
        await redis_client.disconnect()


if __name__ == "__main__":
    import asyncio
    asyncio.run(run_budget_agent_standalone())