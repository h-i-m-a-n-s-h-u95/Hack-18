"""
Budget Agent Implementation with LangChain Tools and Redis Pub/Sub

Follows the same structure as WeatherAgent, MapsAgent, and EventsAgent:
- Extends BaseAgent
- Uses LangChain tools for budget calculations
- Supports MCP protocol via Redis pub/sub
- Streaming updates
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
    """
    Budget Agent - Financial planning and cost estimation
    
    Uses LangChain tools and Google Gemini for intelligent budget recommendations
    """
    
    def __init__(
        self,
        redis_client: RedisClient,
        gemini_api_key: str = None,
        model_name: str = "gemini-2.0-flash-exp"
    ):
        super().__init__(
            name="Quartermaster",
            role="Budget Planner & Financial Advisor",
            expertise="Cost estimation, budget optimization, and financial planning for travel",
            agent_type=AgentType.BUDGET,
            redis_client=redis_client,
            tools=BUDGET_TOOLS,
            gemini_api_key=gemini_api_key,
            model_name=model_name
        )
        
        self.budget_service = BudgetService()
    
    def get_system_prompt(self) -> str:
        """Get the system prompt for the budget agent"""
        return f"""
You are {self.name}, a {self.role}. Your role is to:

1. Analyze travel costs across all categories (transport, accommodation, food, activities)
2. Provide practical budget recommendations based on traveler preferences
3. Suggest cost-saving opportunities and alternatives
4. Warn about potential hidden costs or budget overruns
5. Recommend budget allocation strategies
6. Provide specific transportation recommendations (train names, booking tips)
7. Optimize budgets for Indian travel context

Expertise: {self.expertise}

You have access to budget tools that can:
- Calculate transportation costs (car, train, bus, taxi)
- Calculate accommodation costs
- Calculate food and dining costs
- Calculate activities and sightseeing costs
- Generate complete budget breakdowns
- Compare costs across budget categories (budget, mid-range, luxury)
- Get detailed cost breakdown information

All costs are in Indian Rupees (INR). Consider Indian travel context:
- Train travel is common and economical (Sleeper, AC 3-Tier, AC 2-Tier classes)
- Budget hotels around ₹1500/night, mid-range ₹3000/night, luxury ₹6000/night
- Food costs: ₹500/day (budget), ₹1200/day (mid-range), ₹2500/day (luxury)
- Activities: ₹300/day (budget), ₹800/day (mid-range), ₹2000/day (luxury)

Always provide practical, money-conscious advice in Indian Rupees.
Consider booking platforms like IRCTC for trains, Make My Trip/GoIbibo for buses.

When analyzing budgets, include:
1. Realistic cost analysis
2. Specific transport recommendations (train names, booking platforms)
3. Optimized budget breakdown
4. Practical money-saving tips
5. Recommended trip duration for budget optimization

IMPORTANT: At the end of your response, provide a JSON block with structured budget data:
```json
{{
    "revised_budget": {{
        "total": number,
        "transportation": number,
        "accommodation": number,
        "food": number,
        "activities": number,
        "contingency": number
    }},
    "recommended_transport": {{
        "mode": "string",
        "details": "string",
        "estimated_cost": number
    }},
    "key_recommendations": [
        "recommendation 1",
        "recommendation 2"
    ],
    "cost_per_person": number,
    "recommended_duration": number
}}
```

Keep responses practical and concise.
"""
    
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle budget request
        
        Expected request payload:
        {
            "destination": "Agra, India",
            "travel_dates": ["2025-07-01", "2025-07-02"],
            "travelers_count": 2,
            "budget_range": "mid-range",  # budget, mid-range, luxury
            "route_data": {...},  # optional
            "distance_km": 200  # optional
        }
        
        Returns:
        {
            "budget_breakdown": {...},
            "budget_analysis": "...",
            "structured_data": {...},
            "transport_recommendations": {...},
            "recommendations": [...],
            "cost_per_person": number,
            "comparison": {...}
        }
        """
        payload = request.get("payload", {})
        session_id = request.get("session_id")
        
        destination = payload.get("destination")
        travel_dates = payload.get("travel_dates", [])
        travelers_count = payload.get("travelers_count", 1)
        budget_range = payload.get("budget_range", "mid-range")
        route_data = payload.get("route_data")
        distance_km = payload.get("distance_km")
        
        # Validate required fields
        if not destination:
            raise ValueError("Missing required field: destination")
        if not travel_dates:
            raise ValueError("Missing required field: travel_dates")
        if travelers_count < 1:
            raise ValueError("travelers_count must be at least 1")
        
        self.log_action("Calculating budget", f"Category: {budget_range}, Travelers: {travelers_count}")
        
# Safe way to handle None
        if budget_range is None:
            budget_category = 'mid-range'
        else:
            budget_category = budget_range.lower()
        if budget_category not in ['budget', 'mid-range', 'luxury', '']:
            budget_category = 'mid-range'


        # Extract distance from route_data if available
        if not distance_km and route_data:
            distance_km = self._extract_distance_km(route_data)
        
        if not distance_km or distance_km <= 0:
            distance_km = 200  # Default assumption
        
        # Determine transport mode from route_data
        transport_mode = "driving"
        if route_data and isinstance(route_data, dict):
            transport_mode = route_data.get("transport_mode", "driving")
        
        # Progress update: Calculating transportation
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Calculating transportation costs",
            progress_percent=25
        )
        
        # Calculate complete budget using tool
        budget_result = await calculate_complete_budget.ainvoke({
            "distance_km": distance_km,
            "transport_mode": transport_mode,
            "travel_dates": travel_dates,
            "travelers_count": travelers_count,
            "budget_category": budget_category
        })
        
        if "error" in budget_result:
            raise Exception(f"Budget calculation failed: {budget_result['error']}")
        
        # Progress update: Analyzing costs
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Analyzing accommodation and activity costs",
            progress_percent=50,
            data={"initial_budget_calculated": True}
        )
        
        # Get budget comparison for context
        comparison_result = await compare_budget_categories.ainvoke({
            "distance_km": distance_km,
            "transport_mode": transport_mode,
            "travel_dates": travel_dates,
            "travelers_count": travelers_count
        })
        
        # Progress update: Generating recommendations
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Generating budget recommendations",
            progress_percent=75
        )
        
        # Generate intelligent budget analysis using LLM
        budget_analysis = await self._generate_budget_analysis(
            budget_result=budget_result,
            comparison_result=comparison_result,
            destination=destination,
            travel_dates=travel_dates,
            travelers_count=travelers_count,
            budget_range=budget_range,
            session_id=session_id
        )
        
        # Extract structured data from LLM response
        structured_data = self._extract_structured_budget_data(budget_analysis)
        
        # Use revised budget if available, otherwise use calculated
        breakdown_dict = budget_result.get("breakdown", {})
        final_budget = {
            "total": budget_result.get("total", 0),
            "transportation": breakdown_dict.get("transportation", {}).get("total", 0),
            "accommodation": breakdown_dict.get("accommodation", {}).get("total", 0),
            "food": breakdown_dict.get("food", {}).get("total", 0),
            "activities": breakdown_dict.get("activities", {}).get("total", 0),
            "currency": "INR"
        }
        
        # Override with LLM recommendations if available
        transport_recommendations = {}
        key_recommendations = []
        
        if structured_data and 'revised_budget' in structured_data:
            revised = structured_data['revised_budget']
            final_budget.update({
                "total": revised.get('total', final_budget["total"]),
                "transportation": revised.get('transportation', final_budget["transportation"]),
                "accommodation": revised.get('accommodation', final_budget["accommodation"]),
                "food": revised.get('food', final_budget["food"]),
                "activities": revised.get('activities', final_budget["activities"]),
            })
            transport_recommendations = structured_data.get('recommended_transport', {})
            key_recommendations = structured_data.get('key_recommendations', [])
        
        # Calculate per person cost
        cost_per_person = final_budget["total"] / travelers_count if travelers_count > 0 else final_budget["total"]
        
        # Progress update: Finalizing
        await self._send_streaming_update(
            session_id=session_id,
            update_type=StreamingUpdateType.PROGRESS,
            message="Finalizing budget report",
            progress_percent=90
        )
        
        self.log_action("Budget analysis complete", f"Total: ₹{final_budget['total']:,.0f}")
        
        return {
            "budget_breakdown": final_budget,
            "budget_analysis": budget_analysis,
            "structured_data": structured_data or {},
            "transport_recommendations": transport_recommendations,
            "recommendations": key_recommendations,
            "cost_per_person": round(cost_per_person, 2),
            "destination": destination,
            "travelers_count": travelers_count,
            "budget_category": budget_category,
            "comparison": comparison_result.get("comparison", {}),
            "days": len(travel_dates),
            "distance_km": distance_km
        }
    
    async def _generate_budget_analysis(
        self,
        budget_result: Dict[str, Any],
        comparison_result: Dict[str, Any],
        destination: str,
        travel_dates: List[str],
        travelers_count: int,
        budget_range: str,
        session_id: str
    ) -> str:
        """Generate intelligent budget analysis using LLM"""
        
        # Format budget data for LLM
        budget_text = self._format_budget_for_llm(budget_result, comparison_result)
        
        user_input = f"""
Destination: {destination}
Travel Dates: {', '.join(travel_dates)} ({len(travel_dates)} days)
Number of Travelers: {travelers_count}
User's Budget Preference: {budget_range}

Current Budget Calculation:
{budget_text}

Please provide:
1. Analysis of whether this budget is realistic for the destination
2. Specific transport recommendations (train names like Shatabdi/Rajdhani, booking platforms)
3. Optimized budget breakdown if current doesn't fit user's stated preference
4. Practical money-saving tips specific to {destination}
5. Recommended trip duration for budget optimization

Remember to include the structured JSON data at the end.
Keep the analysis concise - 4-5 sentences maximum, then provide JSON.
"""
        
        try:
            analysis = await self.invoke_llm(
                system_prompt=self.get_system_prompt(),
                user_input=user_input,
                session_id=session_id,
                stream_progress=False  # Already sent progress updates
            )
            return analysis
        except Exception as e:
            self.log_error("Failed to generate budget analysis", str(e))
            return self._get_fallback_summary(budget_result)
    
    def _format_budget_for_llm(
        self,
        budget_result: Dict[str, Any],
        comparison_result: Dict[str, Any]
    ) -> str:
        """Format budget data for LLM consumption"""
        total = budget_result.get("total", 0)
        breakdown = budget_result.get("breakdown", {})
        
        formatted_lines = [
            f"SELECTED CATEGORY: {budget_result.get('budget_category', 'mid-range').upper()}",
            f"TOTAL BUDGET: ₹{total:,.0f} INR",
            f"",
            f"BREAKDOWN:",
            f"  Transportation: ₹{breakdown.get('transportation', {}).get('total', 0):,.0f}",
            f"  Accommodation: ₹{breakdown.get('accommodation', {}).get('total', 0):,.0f}",
            f"  Food: ₹{breakdown.get('food', {}).get('total', 0):,.0f}",
            f"  Activities: ₹{breakdown.get('activities', {}).get('total', 0):,.0f}",
            f"",
            f"PER PERSON: ₹{budget_result.get('per_person', 0):,.0f}",
            f""
        ]
        
        # Add comparison if available
        if comparison_result and "comparison" in comparison_result:
            formatted_lines.append("CATEGORY COMPARISON:")
            for category, data in comparison_result["comparison"].items():
                formatted_lines.append(f"  {category.upper()}: ₹{data.get('total', 0):,.0f} total")
        
        return "\n".join(formatted_lines)
    
    def _get_fallback_summary(self, budget_result: Dict[str, Any]) -> str:
        """Generate basic fallback summary if LLM fails"""
        total = budget_result.get("total", 0)
        travelers = budget_result.get("travelers_count", 1)
        per_person = budget_result.get("per_person", 0)
        
        return (
            f"Total estimated cost: ₹{total:,.0f} for {travelers} travelers "
            f"(₹{per_person:,.0f} per person). Budget includes transportation, "
            f"accommodation, food, and activities. Book trains via IRCTC and hotels "
            f"via MakeMyTrip for best rates."
        )
    
    def _extract_structured_budget_data(self, llm_response: str) -> Optional[Dict[str, Any]]:
        """Extract structured JSON data from LLM response"""
        try:
            # Look for JSON code blocks
            json_match = re.search(r'```json\s*(\{.*?\})\s*```', llm_response, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
                return json.loads(json_str)
            
            # Alternative: look for JSON-like structures
            json_match = re.search(r'\{[^{}]*"revised_budget"[^{}]*\{.*?\}[^{}]*\}', llm_response, re.DOTALL)
            if json_match:
                return json.loads(json_match.group(0))
                
        except json.JSONDecodeError as e:
            self.logger.warning(f"Failed to parse structured data from LLM: {e}")
        except Exception as e:
            self.logger.error(f"Error extracting structured data: {e}")
        
        return None
    
    def _extract_distance_km(self, route_data: Dict[str, Any]) -> float:
        """Extract distance in kilometers from route data"""
        if not route_data:
            return 0
        
        # Check if distance_meters exists
        distance_m = route_data.get("distance_meters")
        if distance_m:
            return distance_m / 1000
        
        # Parse distance string
        distance_str = route_data.get("distance", "")
        if not distance_str:
            return 0
        
        # Look for km
        km_match = re.search(r'(\d+(?:\.\d+)?)\s*km', distance_str.lower())
        if km_match:
            return float(km_match.group(1))
        
        # Look for meters
        m_match = re.search(r'(\d+(?:\.\d+)?)\s*m', distance_str.lower())
        if m_match:
            return float(m_match.group(1)) / 1000
        
        return 0


# ==================== STANDALONE RUNNER ====================

async def run_budget_agent_standalone():
    """Run the budget agent as a standalone service"""
    from app.messaging.redis_client import get_redis_client, RedisChannels
    from app.config.settings import settings
    
    # Get Redis client
    redis_client = get_redis_client()
    await redis_client.connect()
    
    # Create budget agent
    budget_agent = BudgetAgent(
        redis_client=redis_client,
        gemini_api_key=settings.google_api_key,
        model_name=settings.model_name
    )
    
    # Start the agent
    await budget_agent.start()
    
    print(f"✅ Budget Agent is running!")
    print(f"   Agent: {budget_agent.name}")
    print(f"   Type: {budget_agent.agent_type.value}")
    print(f"   Listening on: {RedisChannels.get_request_channel('budget')}")
    print(f"\nPress Ctrl+C to stop...")
    
    try:
        # Keep running
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        print("\n\n🛑 Shutting down Budget Agent...")
        await budget_agent.stop()
        await redis_client.disconnect()
        print("✅ Budget Agent stopped")


if __name__ == "__main__":
    import asyncio
    from app.messaging.redis_client import RedisChannels
    
    asyncio.run(run_budget_agent_standalone())